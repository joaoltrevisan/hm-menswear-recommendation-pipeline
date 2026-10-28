"""Dedicated session ownership and safe recovery; no age-based liveness guesses."""

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from hm_menswear.db import connect
from hm_menswear.safety import PipelineError, assert_log_safety

TERMINAL = {"prepared", "succeeded", "noop", "failed", "interrupted"}
PREPARATION_LOCK = 684221902118


def ownership_key(run_id):
    return int.from_bytes(
        hashlib.blake2b(UUID(str(run_id)).bytes, digest_size=8).digest(), "big", signed=True
    )


def owned_connection(settings, run_id):
    conn = connect(settings.dsn, autocommit=True)
    try:
        assert_log_safety(conn)
        conn.execute("SELECT set_config('TimeZone','UTC',false)")
        conn.execute("SELECT pg_advisory_lock(%s)", (ownership_key(run_id),))
        return conn
    except BaseException:
        conn.close()
        raise


def log_event(work_dir, run_id, operation, status, *, code=None, counts=None):
    # Explicit scalar schema, never exceptions, DSNs, input paths or customer identifiers.
    if code is not None and not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", code):
        code = "operation_failed"
    event = {
        "time": datetime.now(UTC).isoformat(),
        "run_id": str(UUID(str(run_id))),
        "operation": operation,
        "status": status,
    }
    if code:
        event["code"] = code
    if counts:
        event["counts"] = {k: int(v) for k, v in counts.items() if isinstance(v, int)}
    directory = Path(work_dir) / "logs"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (directory / "operations.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, sort_keys=True) + "\n")
    (directory / "operations.jsonl").chmod(0o600)


def recover_run(settings, run_id, *, failure_code=None):
    run_id = UUID(str(run_id))
    with connect(settings.dsn, autocommit=True) as conn:
        assert_log_safety(conn)
        key = ownership_key(run_id)
        if not conn.execute("SELECT pg_try_advisory_lock(%s)", (key,)).fetchone()[0]:
            return {"run_id": str(run_id), "status": "owned"}
        try:
            with conn.transaction():
                conn.execute(
                    "SELECT active_release_id FROM control.lineage WHERE singleton FOR UPDATE"
                )
                row = conn.execute(
                    "SELECT status,operation,preparation_id FROM control.runs WHERE run_id=%s FOR UPDATE",
                    (run_id,),
                ).fetchone()
                if row is None:
                    return {"run_id": str(run_id), "status": "not_found"}
                status, operation, prep = row
                if status not in TERMINAL:
                    status = "failed" if failure_code else "interrupted"
                    code = failure_code or "abandoned_attempt"
                    conn.execute(
                        "UPDATE control.runs SET status=%s,error_code=%s,ended_at=clock_timestamp() WHERE run_id=%s AND status NOT IN (%s,%s,%s,%s,%s)",
                        (status, code, run_id, *sorted(TERMINAL)),
                    )
                    if operation == "prepare":
                        conn.execute(
                            "UPDATE control.preparations SET status='failed',error_code=%s,completed_at=clock_timestamp() WHERE preparation_id=%s AND status='preparing'",
                            (code, prep),
                        )
            return {"run_id": str(run_id), "status": status}
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (key,))


def record_failure(settings, conn, run_id, operation, exception):
    code = str(exception) if isinstance(exception, PipelineError) else "operation_failed"
    if conn is not None:
        conn.close()  # Never reconnect and continue an old attempt.
    try:
        result = recover_run(settings, run_id, failure_code=code)
    except Exception:
        result = {"run_id": str(run_id), "status": "recovery_required"}
    log_event(
        settings.work_dir,
        run_id,
        operation,
        result["status"],
        code="commit_outcome_verified"
        if result["status"] in {"prepared", "succeeded", "noop"}
        else code,
    )
    return result
