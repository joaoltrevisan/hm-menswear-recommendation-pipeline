"""Synthetic configuration values, not real credentials or customer data."""

import json

import pytest

from hm_menswear.cli import main
from hm_menswear.config import ConfigurationError, Settings


@pytest.fixture
def env(tmp_path):
    return {
        "HM_RAW_DIR": str(tmp_path / "raw"),
        "HM_WORK_DIR": str(tmp_path / "work"),
        "HM_DATABASE_DSN": "dbname=synthetic password=SYNTHETIC_SECRET_SENTINEL",
    }


def test_configuration_repr_and_cli_do_not_echo_secrets(env, monkeypatch, capsys):
    settings = Settings.from_env("loader", env)
    assert settings.chunk_size == 100000
    assert "SYNTHETIC_SECRET_SENTINEL" not in repr(settings)
    assert env["HM_RAW_DIR"] not in repr(settings)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert main(["check-config"]) == 0
    output = capsys.readouterr().out
    assert json.loads(output) == {"status": "valid", "purpose": "loader", "chunk_size": 100000}
    assert "SYNTHETIC_SECRET_SENTINEL" not in output
    assert env["HM_RAW_DIR"] not in output


@pytest.mark.parametrize("key", ["HM_RAW_DIR", "HM_WORK_DIR", "HM_DATABASE_DSN"])
def test_missing_required_configuration_is_safe(env, key):
    del env[key]
    with pytest.raises(ConfigurationError, match="invalid_or_missing_configuration"):
        Settings.from_env("loader", env)


@pytest.mark.parametrize("value", ["", "99", "1000001", "1.5", "NaN"])
def test_invalid_chunks_are_rejected(env, value):
    env["HM_CHUNK_SIZE"] = value
    with pytest.raises(ConfigurationError):
        Settings.from_env("loader", env)


@pytest.mark.parametrize("relation", ["same", "nested_work", "nested_raw"])
def test_raw_and_work_must_be_disjoint(env, relation):
    if relation == "same":
        env["HM_WORK_DIR"] = env["HM_RAW_DIR"]
    elif relation == "nested_work":
        env["HM_WORK_DIR"] = env["HM_RAW_DIR"] + "/nested"
    else:
        env["HM_RAW_DIR"] = env["HM_WORK_DIR"] + "/nested"
    with pytest.raises(ConfigurationError, match="disjoint"):
        Settings.from_env("loader", env)


def test_malformed_dsn_is_not_echoed(env, monkeypatch, capsys):
    env["HM_DATABASE_DSN"] = "SYNTHETIC_SECRET_SENTINEL invalid dsn"
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert main(["check-config"]) == 2
    assert "SYNTHETIC_SECRET_SENTINEL" not in capsys.readouterr().out


def test_env_file_is_not_implicitly_loaded(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("HM_DATABASE_DSN=dbname=synthetic\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("HM_DATABASE_DSN", raising=False)
    with pytest.raises(ConfigurationError):
        Settings.from_env("loader")


def test_pipeline_commands_are_not_implemented_yet():
    with pytest.raises(SystemExit) as exc:
        main(["load"])
    assert exc.value.code == 2


def test_database_failure_is_sanitized(env, monkeypatch, capsys):
    import psycopg

    import hm_menswear.cli as cli

    env["HM_MIGRATION_DSN"] = env["HM_DATABASE_DSN"]
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    def fail(*args, **kwargs):
        raise psycopg.OperationalError("SYNTHETIC_SECRET_SENTINEL connection details")

    monkeypatch.setattr(cli, "connect", fail)
    assert main(["db", "migrate"]) == 3
    output = capsys.readouterr().out
    assert "SYNTHETIC_SECRET_SENTINEL" not in output
    assert json.loads(output)["code"] == "database_operation_failed"
