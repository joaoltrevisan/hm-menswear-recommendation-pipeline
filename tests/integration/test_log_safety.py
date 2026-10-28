"""Mandatory pre-load gate: failing synthetic values must not enter server logs."""

import os
import subprocess
import uuid
from datetime import UTC, datetime

import psycopg
import pytest
from conftest import synthetic_preparation, synthetic_release

from hm_menswear.safety import assert_log_safety

pytestmark = pytest.mark.integration


def test_failing_copy_and_error_values_absent_from_container_logs(migrated):
    container = os.environ.get("HM_TEST_CONTAINER")
    if not container:
        pytest.skip("Set HM_TEST_CONTAINER for the mandatory Docker server-log gate")
    since = datetime.now(UTC).isoformat()
    marker = "SYNTHETIC_LOG_SENTINEL_" + uuid.uuid4().hex
    with migrated.connect("loader") as conn:
        assert_log_safety(conn)
        release, _ = synthetic_release(conn)
        prep = synthetic_preparation(conn, release, complete=False)
        with pytest.raises(psycopg.Error), conn.transaction():
            conn.execute("SELECT %s::integer", (marker,))
        with pytest.raises(psycopg.Error), conn.transaction():
            with conn.cursor().copy(
                "COPY staging.purchase_records(preparation_id,source_record_number,purchase_date,customer_id,article_id,price_source_units,sales_channel_code,disposition) FROM STDIN"
            ) as copy:
                copy.write_row((prep, 1, marker, marker, "0000000001", 1, "1", "menswear"))
        with pytest.raises(psycopg.Error), conn.transaction():
            with conn.cursor().copy(
                "COPY staging.purchase_records(preparation_id,source_record_number,customer_id,disposition) FROM STDIN"
            ) as copy:
                copy.write_row((prep, 2, marker, marker))
    result = subprocess.run(
        ["docker", "logs", "--since", since, container], capture_output=True, text=True, check=True
    )
    assert marker not in result.stdout and marker not in result.stderr
