"""Finite historical schedule, gap filling and bounded safe retry behavior."""

from datetime import date
from unittest.mock import Mock

import psycopg
import pytest

from hm_menswear.jobs import load_next, next_window
from hm_menswear.safety import PipelineError


def d(day):
    return date(2020, 9, day)


def test_gap_union_clipping_and_finite_end():
    assert next_window(d(1), d(23), [], 7) == (d(1), d(8))
    assert next_window(d(1), d(23), [(d(1), d(8)), (d(6), d(12)), (d(15), d(23))], 7) == (
        d(12),
        d(15),
    )
    assert next_window(d(1), d(23), [(d(1), d(20))], 7) == (d(20), d(23))
    assert next_window(d(1), d(23), [(d(1), d(23))], 7) is None


def test_transient_retry_is_bounded_without_echoing_exception(monkeypatch):
    call = Mock(
        side_effect=[
            psycopg.OperationalError("synthetic-secret"),
            psycopg.errors.DeadlockDetected("synthetic-secret"),
            {"status": "noop"},
        ]
    )
    plan = Mock(return_value=(d(1), d(8)))
    monkeypatch.setattr("hm_menswear.jobs.plan_next_window", plan)
    monkeypatch.setattr("hm_menswear.jobs.publish_planned_window", call)
    waits = []
    assert load_next(None, "synthetic", sleep=waits.append) == {
        "status": "noop",
        "retry_count": 2,
    }
    assert waits == [1, 2] and call.call_count == 3
    assert plan.call_count == 1
    assert all(c.args[2] == (d(1), d(8)) for c in call.call_args_list)
    call.side_effect = psycopg.OperationalError("synthetic-secret")
    with pytest.raises(psycopg.OperationalError):
        load_next(None, "synthetic", sleep=lambda _: None)
    assert call.call_count == 6


def test_contract_failure_is_not_retried(monkeypatch):
    call = Mock(side_effect=PipelineError("synthetic_contract_failure"))
    plan = Mock(return_value=(d(1), d(8)))
    monkeypatch.setattr("hm_menswear.jobs.plan_next_window", plan)
    monkeypatch.setattr("hm_menswear.jobs.publish_planned_window", call)
    with pytest.raises(PipelineError):
        load_next(None, "synthetic", sleep=lambda _: pytest.fail("must not sleep"))
    assert call.call_count == 1
