"""Register pinned releases and publish verified preparation staging atomically."""

import json
import uuid
from pathlib import Path

from psycopg import sql

from hm_menswear.extraction.source import capture_sources
from hm_menswear.loading.lifecycle import (
    PREPARATION_LOCK,
    log_event,
    owned_connection,
    record_failure,
)
from hm_menswear.safety import PipelineError
from hm_menswear.transformation.prepare import build_artifact, open_artifact

IDENTITY_NAMESPACE = uuid.UUID("7925b9b3-7409-4ea3-8203-df2125accd7f")


def copy_rows(conn, table, columns, rows):
    query = sql.SQL("COPY {} ({}) FROM STDIN").format(
        sql.Identifier(*table.split(".")), sql.SQL(",").join(map(sql.Identifier, columns))
    )
    with conn.cursor().copy(query) as copy:
        for row in rows:
            copy.write_row(row)


def register_release(conn, manifest):
    release = uuid.uuid5(IDENTITY_NAMESPACE, manifest["manifest_sha256"])
    active = conn.execute(
        "SELECT active_release_id FROM control.lineage WHERE singleton FOR UPDATE"
    ).fetchone()[0]
    if active is not None and active != release:
        raise PipelineError("changed_snapshot_or_contract_requires_replacement")
    existing = conn.execute(
        "SELECT manifest_sha256 FROM control.releases WHERE release_id=%s", (release,)
    ).fetchone()
    if not existing:
        conn.execute(
            "INSERT INTO control.releases(release_id,manifest_sha256,parser_version,validation_version,scope_version,contract_version) VALUES(%s,%s,%s,%s,%s,%s)",
            (
                release,
                manifest["manifest_sha256"],
                *[
                    manifest[k]
                    for k in [
                        "parser_version",
                        "validation_version",
                        "scope_version",
                        "contract_version",
                    ]
                ],
            ),
        )
        for name, info in manifest["files"].items():
            role = {
                "articles.csv": "articles",
                "customers.csv": "customers",
                "transactions_train.csv": "transactions",
            }[name]
            file_id = uuid.uuid5(
                IDENTITY_NAMESPACE, manifest["namespace"] + ":" + role + ":" + info["sha256"]
            )
            conn.execute(
                "INSERT INTO control.source_files(file_id,namespace,role,sha256,byte_size,private_location) VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(file_id) DO NOTHING",
                (file_id, manifest["namespace"], role, info["sha256"], info["bytes"], info["path"]),
            )
            conn.execute(
                "INSERT INTO control.release_files VALUES(%s,%s,%s)", (release, role, file_id)
            )
    if active is None:
        conn.execute("UPDATE control.lineage SET active_release_id=%s WHERE singleton", (release,))
    return release


def stage_artifact(conn, preparation_id, db):
    copy_rows(
        conn,
        "staging.articles",
        ["preparation_id", "source_record_number", "article_id", "attributes"],
        (
            (preparation_id, *row)
            for row in db.execute(
                "SELECT ordinal,article_id,attributes FROM catalog WHERE scope='Menswear' AND identity_valid AND scope_valid"
            )
        ),
    )
    copy_rows(
        conn,
        "staging.customers",
        ["preparation_id", "source_record_number", "customer_id", "attributes"],
        (
            (preparation_id, *row)
            for row in db.execute("""SELECT c.ordinal,c.customer_id,c.attributes
                  FROM customers c JOIN (SELECT DISTINCT customer_id FROM purchases) p USING(customer_id)""")
        ),
    )
    copy_rows(
        conn,
        "staging.purchase_records",
        [
            "preparation_id",
            "source_record_number",
            "purchase_date",
            "customer_id",
            "article_id",
            "price_source_units",
            "sales_channel_code",
            "disposition",
        ],
        (
            (preparation_id, *row, "menswear")
            for row in db.execute("SELECT * FROM purchases ORDER BY ordinal")
        ),
    )
    copy_rows(
        conn,
        "staging.customer_observations",
        ["preparation_id", "customer_id", "first_observed_date", "source_record_number"],
        (
            (preparation_id, *row)
            for row in db.execute("SELECT customer_id,first_date,ordinal FROM observations")
        ),
    )
    copy_rows(
        conn,
        "quality.rejections",
        ["preparation_id", "role", "source_record_number", "primary_reason", "additional_reasons"],
        (
            (preparation_id, role, ordinal, reason, json.loads(extra))
            for role, ordinal, reason, extra in db.execute("SELECT * FROM rejections")
        ),
    )


def prepare_dataset(settings, *, contract=None, pinned=True, hook=None, filenames=None):
    run_id = uuid.uuid4()
    conn = None
    log_event(settings.work_dir, run_id, "prepare", "started")
    try:
        conn = owned_connection(settings, run_id)
        manifest = capture_sources(
            settings.raw_dir,
            settings.work_dir,
            contract=contract,
            pinned=pinned,
            filenames=filenames,
        )
        conn.execute("SELECT pg_advisory_lock(%s)", (PREPARATION_LOCK,))
        with conn.transaction():
            release = register_release(conn, manifest)
            complete = conn.execute(
                "SELECT preparation_id,private_location,artifact_sha256 FROM control.preparations WHERE release_id=%s AND status='complete' ORDER BY started_at LIMIT 1",
                (release,),
            ).fetchone()
            prep = complete[0] if complete else uuid.uuid4()
            final = Path(settings.work_dir) / "preparations" / str(prep)
            if not complete:
                conn.execute(
                    "INSERT INTO control.preparations(preparation_id,release_id,status,private_location) VALUES(%s,%s,'preparing',%s)",
                    (prep, release, str(final / "prepared.sqlite")),
                )
            conn.execute(
                "INSERT INTO control.runs(run_id,release_id,status,operation,preparation_id) VALUES(%s,%s,'preparing','prepare',%s)",
                (run_id, release, prep),
            )
        if complete:
            db = open_artifact(complete[1], complete[2])
            db.close()
            with conn.transaction():
                conn.execute(
                    "UPDATE control.runs SET status='prepared',ended_at=clock_timestamp() WHERE run_id=%s",
                    (run_id,),
                )
            log_event(settings.work_dir, run_id, "prepare", "prepared")
            return {
                "run_id": str(run_id),
                "preparation_id": str(prep),
                "release_id": str(release),
                "status": "prepared",
                "reused": True,
            }
        partial = final.with_name(final.name + ".partial")
        metadata = build_artifact(manifest, partial, settings.chunk_size)
        partial.replace(final)
        if hook:
            hook("after_artifact", conn)
        summary = metadata["summary"]
        db = open_artifact(final / "prepared.sqlite", summary["artifact_sha256"])
        try:
            with conn.transaction():
                conn.execute(
                    "SELECT active_release_id FROM control.lineage WHERE singleton FOR UPDATE"
                )
                stage_artifact(conn, prep, db)
                actual = conn.execute(
                    "SELECT count(*) FROM staging.purchase_records WHERE preparation_id=%s", (prep,)
                ).fetchone()[0]
                expected = {
                    "staging.articles": summary["menswear_products"],
                    "staging.customers": summary["distinct_menswear_customers"],
                    "staging.customer_observations": summary["customer_observations"],
                    "quality.rejections": summary["rejected_rows"]
                    + sum(summary["dimension_rejections"].values()),
                }
                if actual != summary["valid_menswear_rows"]:
                    raise PipelineError("staging_reconciliation_failed")
                for table, count in expected.items():
                    observed = conn.execute(
                        sql.SQL("SELECT count(*) FROM {} WHERE preparation_id=%s").format(
                            sql.Identifier(*table.split("."))
                        ),
                        (prep,),
                    ).fetchone()[0]
                    if observed != count:
                        raise PipelineError("staging_reconciliation_failed")
                if hook:
                    hook("after_staging", conn)
                conn.execute(
                    "UPDATE control.preparations SET status='complete',artifact_sha256=%s,source_rows=%s,rejected_rows=%s,valid_out_of_scope_rows=%s,valid_menswear_rows=%s,completed_at=clock_timestamp() WHERE preparation_id=%s",
                    (
                        summary["artifact_sha256"],
                        *[
                            summary[k]
                            for k in [
                                "source_rows",
                                "rejected_rows",
                                "valid_out_of_scope_rows",
                                "valid_menswear_rows",
                            ]
                        ],
                        prep,
                    ),
                )
                conn.execute(
                    "UPDATE control.runs SET status='prepared',ended_at=clock_timestamp() WHERE run_id=%s",
                    (run_id,),
                )
        finally:
            db.close()
        log_event(settings.work_dir, run_id, "prepare", "prepared", counts=summary)
        return {
            "run_id": str(run_id),
            "preparation_id": str(prep),
            "release_id": str(release),
            "status": "prepared",
            "reused": False,
            "summary": summary,
        }
    except BaseException as exc:
        result = record_failure(settings, conn, run_id, "prepare", exc)
        if result["status"] == "prepared":
            return {**result, "commit_verified": True}
        raise
    finally:
        if conn is not None:
            conn.close()
