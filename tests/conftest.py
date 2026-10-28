"""Test controls: all integration records are independently synthetic."""

import os

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--require-postgres",
        action="store_true",
        help="Fail rather than skip if the isolated PostgreSQL DSN is absent",
    )


def pytest_configure(config):
    if config.getoption("--require-postgres") and not os.environ.get("HM_TEST_ADMIN_DSN"):
        raise pytest.UsageError("HM_TEST_ADMIN_DSN is required; its value must remain private")
