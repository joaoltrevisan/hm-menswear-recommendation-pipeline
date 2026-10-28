"""Explicit environment configuration with safe error messages and repr."""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from psycopg import ProgrammingError
from psycopg.conninfo import conninfo_to_dict


class ConfigurationError(ValueError):
    """A safe configuration failure, without echoing input values."""


DSN_VARIABLES = {
    "loader": "HM_DATABASE_DSN",
    "migration": "HM_MIGRATION_DSN",
    "admin": "HM_ADMIN_DSN",
    "model": "HM_MODEL_DSN",
    "reader": "HM_READER_DSN",
}


@dataclass(frozen=True)
class Settings:
    raw_dir: Path = field(repr=False)
    work_dir: Path = field(repr=False)
    chunk_size: int
    dsn: str = field(repr=False)
    purpose: str

    @classmethod
    def from_env(cls, purpose: str, env: Mapping[str, str] | None = None) -> "Settings":
        values = os.environ if env is None else env
        if purpose not in DSN_VARIABLES:
            raise ConfigurationError("unsupported_connection_purpose")
        try:
            raw = Path(values["HM_RAW_DIR"]).expanduser().resolve()
            work = Path(values["HM_WORK_DIR"]).expanduser().resolve()
            if not values["HM_RAW_DIR"].strip() or not values["HM_WORK_DIR"].strip():
                raise ValueError
            chunk = int(values.get("HM_CHUNK_SIZE", "100000"))
            if not 100 <= chunk <= 1_000_000:
                raise ValueError
            dsn = values[DSN_VARIABLES[purpose]]
            if not dsn.strip():
                raise ValueError
            conninfo_to_dict(dsn)
        except (KeyError, ValueError, OSError, ProgrammingError):
            # libpq parsing exceptions can contain DSNs: never propagate their text.
            raise ConfigurationError("invalid_or_missing_configuration") from None
        if raw == work or raw.is_relative_to(work) or work.is_relative_to(raw):
            raise ConfigurationError("raw_and_work_directories_must_be_disjoint")
        return cls(raw, work, chunk, dsn, purpose)
