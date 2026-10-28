"""One atomic dated publication, canonical source identities, and overlap reconciliation."""

import json
import uuid
from datetime import date, timedelta

from psycopg import sql

from hm_menswear.db import connect
from hm_menswear.extraction.source import source_contract
from hm_menswear.loading.lifecycle import log_event, owned_connection, record_failure
from hm_menswear.safety import PipelineError, assert_log_safety
from hm_menswear.transformation.prepare import open_artifact
from hm_menswear.validation.values import valid_date


def publish_dimension(
    conn, preparation, release, table, key, columns, expressions, extra="", params=()
):
    selected = sql.SQL(",").join(
        sql.SQL(expression) + sql.SQL(" AS ") + sql.Identifier(column)
        for column, expression in zip(columns, expressions, strict=True)
    )
    incoming = sql.SQL("SELECT {} FROM {} s WHERE preparation_id=%s {}").format(
        selected, sql.Identifier("staging", table), sql.SQL(extra)
    )
    fields = sql.SQL(",").join(map(sql.Identifier, columns))
    left = sql.SQL(",").join(sql.Identifier("m", c) for c in columns)
    right = sql.SQL(",").join(sql.Identifier("i", c) for c in columns)
    mismatch = sql.SQL(
        "WITH incoming AS ({}) SELECT EXISTS(SELECT 1 FROM incoming i JOIN {} m ON m.release_id=%s AND m.{}=i.{} WHERE ROW({}) IS DISTINCT FROM ROW({}))"
    ).format(
        incoming,
        sql.Identifier("mart", table),
        sql.Identifier(key),
        sql.Identifier(key),
        left,
        right,
    )
    if conn.execute(mismatch, (preparation, *params, release)).fetchone()[0]:
        raise PipelineError("existing_dimension_payload_mismatch")
    query = sql.SQL(
        "WITH incoming AS ({}) INSERT INTO {}(release_id,{}) SELECT %s,{} FROM incoming ON CONFLICT(release_id,{}) DO NOTHING"
    ).format(incoming, sql.Identifier("mart", table), fields, fields, sql.Identifier(key))
    conn.execute(query, (preparation, *params, release))


def publish_dimensions(conn, prep, release, start, end):
    article_fields = source_contract()["files"]["articles.csv"]["columns"]
    columns = ["source_record_number", *article_fields]
    expressions = [
        "s.source_record_number",
        "s.article_id",
        *["s.attributes->>'" + field + "'" for field in article_fields[1:]],
    ]
    publish_dimension(conn, prep, release, "articles", "article_id", columns, expressions)
    columns = [
        "source_record_number",
        "customer_id",
        "fn",
        "active",
        "club_member_status",
        "fashion_news_frequency",
        "age",
    ]
    expressions = [
        "s.source_record_number",
        "s.customer_id",
        "s.attributes->>'FN'",
        "s.attributes->>'Active'",
        "s.attributes->>'club_member_status'",
        "s.attributes->>'fashion_news_frequency'",
        "(s.attributes->>'age')::numeric::integer",
    ]
    extra = "AND EXISTS(SELECT 1 FROM staging.purchase_records p WHERE p.preparation_id=%s AND p.customer_id=s.customer_id AND p.purchase_date >= %s AND p.purchase_date < %s)"
    publish_dimension(
        conn,
        prep,
        release,
        "customers",
        "customer_id",
        columns,
        expressions,
        extra,
        (prep, start, end),
    )


def load_window(settings, preparation_id, start, end, *, hook=None):
    if not valid_date(start) or not valid_date(end) or start >= end:
        raise PipelineError("invalid_half_open_window")
    prep = uuid.UUID(str(preparation_id))
    run_id = uuid.uuid4()
    conn = None
    batch_id = None
    log_event(settings.work_dir, run_id, "load", "started")
    try:
        conn = owned_connection(settings, run_id)
        ready = conn.execute(
            "SELECT release_id,private_location,artifact_sha256 FROM control.preparations WHERE preparation_id=%s AND status='complete'",
            (prep,),
        ).fetchone()
        if ready is None:
            raise PipelineError("complete_preparation_required")
        release, path, digest = ready
        conn.execute(
            "INSERT INTO control.runs(run_id,release_id,status,operation,preparation_id) VALUES(%s,%s,'waiting_to_publish','load',%s)",
            (run_id, release, prep),
        )
        artifact = open_artifact(path, digest)
        artifact.close()
        if hook:
            hook("waiting", conn)
        with conn.transaction():
            active = conn.execute(
                "SELECT active_release_id FROM control.lineage WHERE singleton FOR UPDATE"
            ).fetchone()[0]
            if active != release:
                raise PipelineError("release_not_active")
            status = conn.execute(
                "SELECT status FROM control.runs WHERE run_id=%s", (run_id,)
            ).fetchone()[0]
            if status != "waiting_to_publish":
                raise PipelineError("attempt_not_publishable")
            assert_log_safety(conn)
            existing = conn.execute(
                "SELECT batch_id,preparation_id,status,accepted_rows,inserted_rows,reused_rows FROM control.batches WHERE release_id=%s AND start_date=%s AND end_date=%s",
                (release, start, end),
            ).fetchone()
            if existing and existing[1] != prep:
                raise PipelineError("batch_preparation_mismatch")
            if existing and existing[2] == "completed":
                batch_id = existing[0]
                conn.execute(
                    "UPDATE control.runs SET batch_id=%s,status='noop',ended_at=clock_timestamp() WHERE run_id=%s",
                    (batch_id, run_id),
                )
                result = {
                    "run_id": str(run_id),
                    "batch_id": str(batch_id),
                    "status": "noop",
                    "accepted_rows": existing[3],
                    "inserted_rows": 0,
                    "reused_rows": existing[3],
                }
            else:
                batch_id = existing[0] if existing else uuid.uuid5(release, start + "/" + end)
                if not existing:
                    conn.execute(
                        "INSERT INTO control.batches(batch_id,release_id,preparation_id,start_date,end_date,status) VALUES(%s,%s,%s,%s,%s,'pending')",
                        (batch_id, release, prep, start, end),
                    )
                conn.execute(
                    "UPDATE control.runs SET batch_id=%s,status='publishing' WHERE run_id=%s",
                    (batch_id, run_id),
                )
                file_id = conn.execute(
                    "SELECT file_id FROM control.release_files WHERE release_id=%s AND role='transactions'",
                    (release,),
                ).fetchone()[0]
                before = conn.execute(
                    "SELECT count(*) FROM mart.purchase_events WHERE release_id=%s", (release,)
                ).fetchone()[0]
                publish_dimensions(conn, prep, release, start, end)
                if hook:
                    hook("after_dimensions", conn)
                params = (prep, start, end)
                incoming = "SELECT source_record_number,article_id,customer_id,purchase_date,price_source_units,sales_channel_code FROM staging.purchase_records WHERE preparation_id=%s AND purchase_date >= %s AND purchase_date < %s"
                mismatch = conn.execute(
                    "WITH incoming AS ("
                    + incoming
                    + ") SELECT EXISTS(SELECT 1 FROM incoming s JOIN mart.purchase_events m ON m.transaction_file_id=%s AND m.source_record_number=s.source_record_number WHERE ROW(m.release_id,m.article_id,m.customer_id,m.purchase_date,m.price_source_units,m.sales_channel_code) IS DISTINCT FROM ROW(%s::uuid,s.article_id,s.customer_id,s.purchase_date,s.price_source_units,s.sales_channel_code))",
                    (*params, file_id, release),
                ).fetchone()[0]
                if mismatch:
                    raise PipelineError("existing_purchase_payload_mismatch")
                accepted = conn.execute(
                    "SELECT count(*) FROM (" + incoming + ") x", params
                ).fetchone()[0]
                inserted = conn.execute(
                    "WITH incoming AS ("
                    + incoming
                    + ") INSERT INTO mart.purchase_events(transaction_file_id,source_record_number,release_id,article_id,customer_id,purchase_date,price_source_units,sales_channel_code,first_batch_id) SELECT %s,source_record_number,%s,article_id,customer_id,purchase_date,price_source_units,sales_channel_code,%s FROM incoming ON CONFLICT(transaction_file_id,source_record_number) DO NOTHING",
                    (*params, file_id, release, batch_id),
                ).rowcount
                if hook:
                    hook("after_facts", conn)
                memberships = conn.execute(
                    "WITH incoming AS ("
                    + incoming
                    + ") INSERT INTO control.batch_records SELECT %s,%s,%s,source_record_number FROM incoming",
                    (*params, batch_id, release, file_id),
                ).rowcount
                mismatch = conn.execute(
                    "SELECT EXISTS(SELECT 1 FROM staging.customer_observations s JOIN mart.customer_observations m ON m.release_id=%s AND m.customer_id=s.customer_id WHERE s.preparation_id=%s AND s.first_observed_date >= %s AND s.first_observed_date < %s AND ROW(m.first_observed_date,m.transaction_file_id,m.source_record_number) IS DISTINCT FROM ROW(s.first_observed_date,%s::uuid,s.source_record_number))",
                    (release, prep, start, end, file_id),
                ).fetchone()[0]
                if mismatch:
                    raise PipelineError("existing_observation_payload_mismatch")
                conn.execute(
                    "INSERT INTO mart.customer_observations(release_id,customer_id,first_observed_date,transaction_file_id,source_record_number,first_batch_id) SELECT %s,customer_id,first_observed_date,%s,source_record_number,%s FROM staging.customer_observations WHERE preparation_id=%s AND first_observed_date >= %s AND first_observed_date < %s ON CONFLICT(release_id,customer_id) DO NOTHING",
                    (release, file_id, batch_id, prep, start, end),
                )
                after = conn.execute(
                    "SELECT count(*) FROM mart.purchase_events WHERE release_id=%s", (release,)
                ).fetchone()[0]
                if accepted != memberships or after - before != inserted or inserted > accepted:
                    raise PipelineError("publication_reconciliation_failed")
                if hook:
                    hook("before_completion", conn)
                conn.execute(
                    "UPDATE control.batches SET status='completed',accepted_rows=%s,inserted_rows=%s,reused_rows=%s,completed_at=clock_timestamp() WHERE batch_id=%s",
                    (accepted, inserted, accepted - inserted, batch_id),
                )
                conn.execute(
                    "UPDATE control.runs SET status='succeeded',ended_at=clock_timestamp() WHERE run_id=%s",
                    (run_id,),
                )
                if hook:
                    hook("before_commit", conn)
                result = {
                    "run_id": str(run_id),
                    "batch_id": str(batch_id),
                    "status": "succeeded",
                    "accepted_rows": accepted,
                    "inserted_rows": inserted,
                    "reused_rows": accepted - inserted,
                }
        if hook:
            hook("after_commit", conn)
        log_event(settings.work_dir, run_id, "load", result["status"], counts=result)
        return result
    except BaseException as exc:
        recovered = record_failure(settings, conn, run_id, "load", exc)
        if recovered["status"] in ("succeeded", "noop") and batch_id:
            with connect(settings.dsn, autocommit=True) as ledger:
                counts = ledger.execute(
                    "SELECT accepted_rows,inserted_rows,reused_rows FROM control.batches WHERE batch_id=%s",
                    (batch_id,),
                ).fetchone()
            return {
                **recovered,
                "batch_id": str(batch_id),
                "accepted_rows": counts[0],
                "inserted_rows": counts[1],
                "reused_rows": counts[2],
                "commit_verified": True,
            }
        raise
    finally:
        if conn is not None:
            conn.close()


def load_all(settings, preparation_id, *, batch_days=7):
    if not 1 <= batch_days <= 366:
        raise PipelineError("invalid_batch_days")
    with connect(settings.dsn, autocommit=True) as conn:
        row = conn.execute(
            "SELECT private_location,artifact_sha256 FROM control.preparations WHERE preparation_id=%s AND status='complete'",
            (uuid.UUID(str(preparation_id)),),
        ).fetchone()
    if not row:
        raise PipelineError("complete_preparation_required")
    artifact = open_artifact(row[0], row[1])
    try:
        summary = json.loads(
            artifact.execute("SELECT value FROM metadata WHERE key='summary'").fetchone()[0]
        )
    finally:
        artifact.close()
    if not summary["date_min"] or not summary["date_max"]:
        raise PipelineError("no_calendar_valid_dates")
    start = date.fromisoformat(summary["date_min"])
    last = date.fromisoformat(summary["date_max"]) + timedelta(days=1)
    totals = {"batches": 0, "accepted_rows": 0, "inserted_rows": 0, "reused_rows": 0}
    while start < last:
        end = min(start + timedelta(days=batch_days), last)
        result = load_window(settings, preparation_id, start.isoformat(), end.isoformat())
        totals["batches"] += 1
        for key in ["accepted_rows", "inserted_rows", "reused_rows"]:
            totals[key] += result[key]
        start = end
    return {"status": "completed", "preparation_id": str(preparation_id), **totals}
