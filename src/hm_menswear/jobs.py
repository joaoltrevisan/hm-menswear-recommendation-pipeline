"""One historical arrival per invocation; bounded transient retry, never live ingestion."""

import json
import time
import uuid
from datetime import date, timedelta

import psycopg

from hm_menswear.db import connect
from hm_menswear.loading.publish import load_window
from hm_menswear.safety import PipelineError
from hm_menswear.transformation.prepare import open_artifact


def next_window(start, end, completed, batch_days):
    cursor = start
    for left, right in sorted(completed):
        if right <= cursor:
            continue
        if left > cursor:
            return cursor, min(cursor + timedelta(days=batch_days), left, end)
        cursor = max(cursor, right)
        if cursor >= end:
            return None
    return (cursor, min(cursor + timedelta(days=batch_days), end)) if cursor < end else None


def plan_next_window(settings, preparation_id, batch_days):
    if not 1 <= batch_days <= 366:
        raise PipelineError("invalid_batch_days")
    with connect(settings.dsn, autocommit=True) as conn:
        row = conn.execute(
            "SELECT release_id,private_location,artifact_sha256 FROM control.preparations WHERE preparation_id=%s AND status='complete'",
            (uuid.UUID(str(preparation_id)),),
        ).fetchone()
        if row is None:
            raise PipelineError("complete_preparation_required")
        completed = conn.execute(
            "SELECT start_date,end_date FROM control.batches WHERE release_id=%s AND status='completed' ORDER BY start_date,end_date",
            (row[0],),
        ).fetchall()
    artifact = open_artifact(row[1], row[2])
    try:
        summary = json.loads(
            artifact.execute("SELECT value FROM metadata WHERE key='summary'").fetchone()[0]
        )
    finally:
        artifact.close()
    if not summary["date_min"] or not summary["date_max"]:
        raise PipelineError("no_calendar_valid_dates")
    window = next_window(
        date.fromisoformat(summary["date_min"]),
        date.fromisoformat(summary["date_max"]) + timedelta(days=1),
        completed,
        batch_days,
    )
    return window


def publish_planned_window(settings, preparation_id, window):
    result = load_window(settings, preparation_id, window[0].isoformat(), window[1].isoformat())
    return {
        **result,
        "start": window[0].isoformat(),
        "end": window[1].isoformat(),
        "historical_simulation": True,
    }


def load_next(settings, preparation_id, *, batch_days=7, attempts=3, sleep=time.sleep):
    if not 1 <= attempts <= 3:
        raise PipelineError("retry_attempts_must_be_1_to_3")
    unplanned = object()
    window = unplanned
    for attempt in range(attempts):
        try:
            if window is unplanned:
                window = plan_next_window(settings, preparation_id, batch_days)
            if window is None:
                return {
                    "status": "source_exhausted",
                    "preparation_id": str(preparation_id),
                    "retry_count": attempt,
                }
            return {
                **publish_planned_window(settings, preparation_id, window),
                "retry_count": attempt,
            }
        except (
            psycopg.OperationalError,
            psycopg.errors.SerializationFailure,
            psycopg.errors.DeadlockDetected,
        ):
            if attempt + 1 == attempts:
                raise
            sleep(2**attempt)
