"""Safe failures and the mandatory server-log configuration gate."""

EXPECTED_LOG_SETTINGS = {
    "log_min_messages": "panic",
    "log_min_error_statement": "panic",
    "log_statement": "none",
    "log_error_verbosity": "terse",
    "log_parameter_max_length": "0",
    "log_parameter_max_length_on_error": "0",
    "log_min_duration_statement": "-1",
    "log_min_duration_sample": "-1",
    "log_transaction_sample_rate": "0",
    "log_duration": "off",
    "log_connections": "off",
    "log_disconnections": "off",
}


class PipelineError(RuntimeError):
    """A stable, payload-free operational code, never a raw input value."""


def assert_log_safety(conn):
    actual = dict(
        conn.execute(
            "SELECT key, current_setting(key) FROM unnest(%s::text[]) key",
            (list(EXPECTED_LOG_SETTINGS),),
        ).fetchall()
    )
    if actual != EXPECTED_LOG_SETTINGS:
        raise PipelineError("unsafe_server_log_configuration")
