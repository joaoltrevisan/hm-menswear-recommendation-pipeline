"""Private disk-indexed preparation; pandas input chunks, no purchase deduplication."""

import itertools
import os
import sqlite3
from collections import Counter
from pathlib import Path

from hm_menswear.extraction.source import canonical_json, digest_file, records
from hm_menswear.safety import PipelineError
from hm_menswear.validation.values import (
    ARTICLE,
    CUSTOMER,
    customer_metadata,
    valid_date,
    valid_price,
)


def build_artifact(manifest, destination, chunk_size):
    destination = Path(destination)
    destination.mkdir(parents=True, mode=0o700)
    db_path = destination / "prepared.sqlite"
    db = sqlite3.connect(db_path)
    db.execute("PRAGMA cache_size=-65536")  # Bound the disk-artifact page cache to 64 MiB.
    os.chmod(db_path, 0o600)
    db.executescript("""
        CREATE TABLE catalog(article_id TEXT PRIMARY KEY,ordinal INTEGER,scope TEXT,
            identity_valid INTEGER,scope_valid INTEGER,attributes TEXT);
        CREATE TABLE customers(customer_id TEXT PRIMARY KEY,ordinal INTEGER,
            identity_valid INTEGER,metadata_valid INTEGER,attributes TEXT);
        CREATE TABLE purchases(ordinal INTEGER PRIMARY KEY,purchase_date TEXT,
            customer_id TEXT,article_id TEXT,price TEXT,channel TEXT);
        CREATE TABLE observations(customer_id TEXT PRIMARY KEY,first_date TEXT,ordinal INTEGER);
        CREATE TABLE rejections(role TEXT,ordinal INTEGER,primary_reason TEXT,additional TEXT,
            PRIMARY KEY(role,ordinal));
    """)
    counts = Counter(
        source_rows=0, rejected_rows=0, valid_out_of_scope_rows=0, valid_menswear_rows=0
    )
    dimension_rejections = Counter()
    try:
        for role, name in [("articles", "articles.csv"), ("customers", "customers.csv")]:
            info = manifest["files"][name]
            seen = 0
            with db:
                for ordinal, row in records(info["path"], info["columns"], chunk_size):
                    seen += 1
                    attrs = {
                        k: (v if v != "" else None)
                        for k, v in zip(info["columns"], row, strict=True)
                    }
                    attrs.pop("postal_code", None)
                    if role == "articles":
                        identity = bool(ARTICLE.fullmatch(row[0]))
                        scope = row[info["columns"].index("index_group_name")]
                        scope_valid = bool(scope)
                        db.execute(
                            "INSERT INTO catalog VALUES(?,?,?,?,?,?)",
                            (row[0], ordinal, scope, identity, scope_valid, canonical_json(attrs)),
                        )
                        valid = identity and scope_valid
                    else:
                        identity = bool(CUSTOMER.fullmatch(row[0]))
                        valid = identity and customer_metadata(row)
                        db.execute(
                            "INSERT INTO customers VALUES(?,?,?,?,?)",
                            (row[0], ordinal, identity, valid, canonical_json(attrs)),
                        )
                    if not valid:
                        dimension_rejections[role] += 1
                        db.execute(
                            "INSERT INTO rejections VALUES(?,?,?,?)",
                            (role, ordinal, "invalid_dimension_record", "[]"),
                        )
            if seen != info["rows"]:
                raise PipelineError("parser_record_count_mismatch")
        catalog = {
            row[0]: row[1:]
            for row in db.execute("SELECT article_id,scope,identity_valid,scope_valid FROM catalog")
        }
        info = manifest["files"]["transactions_train.csv"]
        stream = records(info["path"], info["columns"], chunk_size)
        date_min = date_max = None
        while rows := list(itertools.islice(stream, chunk_size)):
            identifiers = list({row[1][1] for row in rows})
            customers = {}
            for start in range(0, len(identifiers), 900):
                group = identifiers[start : start + 900]
                query = (
                    "SELECT customer_id,identity_valid,metadata_valid FROM customers WHERE customer_id IN ("
                    + ",".join("?" for _ in group)
                    + ")"
                )
                customers.update((row[0], row[1:]) for row in db.execute(query, group))
            purchases = []
            rejections = []
            observations = {}
            for ordinal, row in rows:
                counts["source_rows"] += 1
                day, customer, article, price, channel = row
                product = catalog.get(article)
                known_customer = customers.get(customer)
                date_ok = valid_date(day)
                identity_ok = bool(ARTICLE.fullmatch(article) and CUSTOMER.fullmatch(customer))
                if date_ok:
                    date_min = min(date_min, day) if date_min else day
                    date_max = max(date_max, day) if date_max else day
                # Observation validity intentionally ignores prices/channels/demographics.
                if (
                    date_ok
                    and identity_ok
                    and product
                    and product[1]
                    and known_customer
                    and known_customer[0]
                ):
                    pair = (day, ordinal)
                    if customer not in observations or pair < observations[customer]:
                        observations[customer] = pair
                reasons = []
                if not all(row):
                    reasons.append("missing_required")
                if not ARTICLE.fullmatch(article):
                    reasons.append("invalid_article_id")
                if not CUSTOMER.fullmatch(customer):
                    reasons.append("invalid_customer_id")
                if not date_ok:
                    reasons.append("invalid_date")
                if not valid_price(price):
                    reasons.append("invalid_price")
                if channel not in ("1", "2"):
                    reasons.append("invalid_channel")
                if product is None:
                    reasons.append("unknown_article_reference")
                elif not product[1] or not product[2]:
                    reasons.append("invalid_catalog_reference")
                if known_customer is None:
                    reasons.append("unknown_customer_reference")
                elif not known_customer[1]:
                    reasons.append("invalid_customer_metadata")
                if reasons:
                    counts["rejected_rows"] += 1
                    rejections.append(
                        ("transactions", ordinal, reasons[0], canonical_json(reasons[1:]))
                    )
                elif product[0] != "Menswear":
                    counts["valid_out_of_scope_rows"] += 1
                else:
                    counts["valid_menswear_rows"] += 1
                    purchases.append((ordinal, day, customer, article, price, channel))
            with db:
                db.executemany("INSERT INTO purchases VALUES(?,?,?,?,?,?)", purchases)
                db.executemany("INSERT INTO rejections VALUES(?,?,?,?)", rejections)
                db.executemany(
                    """INSERT INTO observations VALUES(?,?,?) ON CONFLICT(customer_id)
                    DO UPDATE SET first_date=excluded.first_date,ordinal=excluded.ordinal
                    WHERE (excluded.first_date,excluded.ordinal)<(observations.first_date,observations.ordinal)""",
                    ((customer, *pair) for customer, pair in observations.items()),
                )
        if counts["source_rows"] != info["rows"] or counts["source_rows"] != sum(
            counts[key]
            for key in ["rejected_rows", "valid_out_of_scope_rows", "valid_menswear_rows"]
        ):
            raise PipelineError("preparation_reconciliation_failed")
        db.executescript("""CREATE INDEX purchase_date ON purchases(purchase_date);
            CREATE INDEX purchase_customer ON purchases(customer_id);
            CREATE INDEX observation_date ON observations(first_date);""")
        duplicate_groups, additional = db.execute("""SELECT count(*),coalesce(sum(n-1),0) FROM
            (SELECT count(*) n FROM purchases GROUP BY purchase_date,customer_id,article_id,price,channel
             HAVING count(*)>1)""").fetchone()
        summary = {
            **dict(counts),
            "dimension_rejections": dict(dimension_rejections),
            "menswear_products": db.execute(
                "SELECT count(*) FROM catalog WHERE scope='Menswear' AND identity_valid AND scope_valid"
            ).fetchone()[0],
            "distinct_menswear_customers": db.execute(
                "SELECT count(DISTINCT customer_id) FROM purchases"
            ).fetchone()[0],
            "customer_observations": db.execute("SELECT count(*) FROM observations").fetchone()[0],
            "identical_purchase_groups": duplicate_groups,
            "additional_identical_occurrences": additional,
            "date_min": date_min,
            "date_max": date_max,
        }
        db.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT)")
        db.execute("INSERT INTO metadata VALUES(?,?)", ("summary", canonical_json(summary)))
        db.commit()
    except sqlite3.IntegrityError:
        raise PipelineError("duplicate_dimension_identifier") from None
    finally:
        db.close()
    # Recheck captured bytes after all reads, rather than trusting a mutable pathname.
    if any(digest_file(info["path"]) != info["sha256"] for info in manifest["files"].values()):
        raise PipelineError("intake_digest_mismatch")
    summary["artifact_sha256"] = digest_file(db_path)
    metadata = {"source": manifest, "summary": summary}
    meta_path = destination / "manifest.json"
    meta_path.write_text(canonical_json(metadata) + "\n")
    meta_path.chmod(0o600)
    db_path.chmod(0o400)
    return metadata


def open_artifact(path, expected_digest):
    path = Path(path)
    if digest_file(path) != expected_digest:
        raise PipelineError("preparation_artifact_digest_mismatch")
    return sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
