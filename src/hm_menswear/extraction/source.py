"""Strict file contracts, immutable intake copies, and bounded pandas records."""

import csv
import hashlib
import json
import os
import shutil
import uuid
from importlib.resources import files
from pathlib import Path

import pandas as pd

from hm_menswear.safety import PipelineError


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest_file(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def source_contract():
    return json.loads(files("hm_menswear").joinpath("source_manifest.json").read_text())


def strict_count(path, expected_columns):
    count = 0
    try:
        with Path(path).open(encoding="utf-8", newline="") as stream:
            reader = csv.reader(stream, strict=True)
            if next(reader, None) != expected_columns:
                raise PipelineError("source_header_mismatch")
            for row in reader:
                if len(row) != len(expected_columns) or any("\x00" in value for value in row):
                    raise PipelineError("corrupt_csv_structure")
                count += 1
    except (csv.Error, UnicodeError):
        raise PipelineError("corrupt_csv_structure") from None
    return count


def capture_sources(raw_dir, work_dir, *, contract=None, pinned=True, filenames=None):
    contract = source_contract() if contract is None else contract
    intake = Path(work_dir) / "source_snapshots"
    intake.mkdir(parents=True, exist_ok=True, mode=0o700)
    manifest = {
        key: contract[key]
        for key in [
            "namespace",
            "parser_version",
            "validation_version",
            "scope_version",
            "contract_version",
        ]
    }
    manifest["files"] = {}
    for name, expected in contract["files"].items():
        original = (Path(raw_dir) / (filenames or {}).get(name, name)).resolve()
        if not original.is_relative_to(Path(raw_dir).resolve()):
            raise PipelineError("source_must_be_inside_raw_directory")
        temporary = intake / (str(uuid.uuid4()) + ".partial")
        try:
            with original.open("rb") as source, temporary.open("xb") as target:
                os.chmod(temporary, 0o600)
                shutil.copyfileobj(source, target, length=1024 * 1024)
                target.flush()
                os.fsync(target.fileno())
            digest = digest_file(temporary)
            size = temporary.stat().st_size
            if pinned and (digest != expected["sha256"] or size != expected["bytes"]):
                raise PipelineError("source_digest_mismatch")
            target = intake / (digest + ".csv")
            if target.exists():
                if digest_file(target) != digest:
                    raise PipelineError("intake_digest_mismatch")
                temporary.unlink()
            else:
                temporary.replace(target)
                target.chmod(0o400)
            rows = strict_count(target, expected["columns"])
            manifest["files"][name] = {
                "sha256": digest,
                "bytes": size,
                "rows": rows,
                "columns": expected["columns"],
                "path": str(target),
            }
        finally:
            temporary.unlink(missing_ok=True)
    identity = {
        **manifest,
        "files": {
            name: {k: v for k, v in info.items() if k != "path"}
            for name, info in manifest["files"].items()
        },
    }
    manifest["manifest_sha256"] = hashlib.sha256(canonical_json(identity).encode()).hexdigest()
    return manifest


def records(path, columns, chunk_size):
    ordinal = 0
    try:
        chunks = pd.read_csv(
            path,
            dtype=str,
            na_filter=False,
            keep_default_na=False,
            skip_blank_lines=False,
            chunksize=chunk_size,
            encoding="utf-8",
            on_bad_lines="error",
        )
        with chunks:
            for frame in chunks:
                if list(frame.columns) != columns:
                    raise PipelineError("source_header_mismatch")
                for row in frame.itertuples(index=False, name=None):
                    ordinal += 1
                    yield ordinal, row
    except (pd.errors.ParserError, UnicodeError, pd.errors.EmptyDataError):
        raise PipelineError("corrupt_csv_structure") from None
