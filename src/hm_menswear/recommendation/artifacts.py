"""Private immutable model packages, verified hashes, and clean-source provenance."""

import hashlib
import json
import platform
import subprocess
import uuid
from importlib.resources import files
from pathlib import Path

import numpy as np
from psycopg.types.json import Jsonb

from hm_menswear.extraction.source import canonical_json, digest_file
from hm_menswear.safety import PipelineError


def code_identity(root=None):
    root = Path.cwd() if root is None else Path(root)
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL
        ).strip()
        scope = ["src", "config", "pyproject.toml", "uv.lock", ".python-version"]
        dirty = subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=all", "--", *scope],
            cwd=root,
            text=True,
        )
        if dirty:
            raise PipelineError("commit_verified_model_code_before_training")
        paths = (
            subprocess.check_output(["git", "ls-files", "-z", "--", *scope], cwd=root)
            .decode()
            .split("\0")
        )
        digest = hashlib.sha256()
        for name in sorted(filter(None, paths)):
            raw = (root / name).read_bytes()
            digest.update(name.encode() + b"\0" + raw + b"\0")
            if name.startswith("src/hm_menswear/"):
                relative = name.removeprefix("src/hm_menswear/")
                if files("hm_menswear").joinpath(relative).read_bytes() != raw:
                    raise PipelineError("installed_code_differs_from_repository")
        return {
            "code_commit": commit,
            "source_tree_sha256": digest.hexdigest(),
            "dependency_lock_sha256": digest_file(root / "uv.lock"),
            "python": platform.python_version(),
            "platform": platform.system(),
            "architecture": platform.machine(),
        }
    except (OSError, subprocess.SubprocessError):
        raise PipelineError("clean_source_repository_required") from None


def save_model(conn, work_dir, snapshot, family, parameters, fitted, protocol, identity):
    root = Path(work_dir) / "models"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = root / ("." + str(uuid.uuid4()) + ".partial")
    temporary.mkdir(mode=0o700)
    arrays = {
        "known_ids": snapshot.known_ids,
        "warm_ids": snapshot.warm_ids,
        "articles": snapshot.articles,
        **fitted,
    }
    path = temporary / "arrays.npz"
    np.savez_compressed(path, **arrays)
    path.chmod(0o600)
    manifest = {
        "format_version": 1,
        "release_id": snapshot.release_id,
        "cutoff": snapshot.cutoff,
        "family": family,
        "parameters": parameters,
        "input_snapshot_sha256": snapshot.fingerprint,
        "input_metadata": snapshot.metadata,
        "protocol_sha256": hashlib.sha256(canonical_json(protocol).encode()).hexdigest(),
        "known_customers": len(snapshot.known_ids),
        "warm_customers": len(snapshot.warm_ids),
        "candidate_count": len(snapshot.articles),
        "training_occurrences": len(snapshot.items),
        "random_seed": protocol["random_seed"],
        "artifacts": {"arrays.npz": digest_file(path)},
        **identity,
    }
    model_id = hashlib.sha256(canonical_json(manifest).encode()).hexdigest()
    target = root / model_id
    envelope = {"model_id": model_id, "manifest": manifest}
    (temporary / "manifest.json").write_text(canonical_json(envelope) + "\n")
    (temporary / "manifest.json").chmod(0o600)
    if target.exists():
        loaded = load_model(work_dir, model_id)
        if loaded["manifest"] != manifest:
            raise PipelineError("model_identity_payload_mismatch")
        path.unlink()
        (temporary / "manifest.json").unlink()
        temporary.rmdir()
    else:
        temporary.replace(target)
    with conn.transaction():
        existing = conn.execute(
            "SELECT manifest,status FROM control.models WHERE model_id=%s", (model_id,)
        ).fetchone()
        if existing:
            if existing[0] != manifest or existing[1] != "complete":
                raise PipelineError("model_registry_payload_mismatch")
        else:
            conn.execute(
                "INSERT INTO control.models(model_id,release_id,cutoff_date,family,config_sha256,input_snapshot_sha256,dependency_lock_sha256,code_commit,manifest,private_location,status,completed_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'complete',clock_timestamp())",
                (
                    model_id,
                    uuid.UUID(snapshot.release_id),
                    snapshot.cutoff,
                    family,
                    hashlib.sha256(canonical_json(parameters).encode()).hexdigest(),
                    snapshot.fingerprint,
                    identity["dependency_lock_sha256"],
                    identity["code_commit"],
                    Jsonb(manifest),
                    str(target),
                ),
            )
    return {"model_id": model_id, "manifest": manifest, "arrays": arrays}


def load_model(work_dir, model_id):
    import re

    if not re.fullmatch(r"[0-9a-f]{64}", model_id):
        raise PipelineError("invalid_model_identifier")
    root = Path(work_dir) / "models" / model_id
    envelope = json.loads((root / "manifest.json").read_text())
    manifest = envelope["manifest"]
    if (
        envelope["model_id"] != model_id
        or hashlib.sha256(canonical_json(manifest).encode()).hexdigest() != model_id
    ):
        raise PipelineError("model_manifest_digest_mismatch")
    if (
        set(manifest["artifacts"]) != {"arrays.npz"}
        or digest_file(root / "arrays.npz") != manifest["artifacts"]["arrays.npz"]
    ):
        raise PipelineError("model_artifact_digest_mismatch")
    with np.load(root / "arrays.npz", allow_pickle=False) as saved:
        arrays = {name: saved[name] for name in saved.files}
    expected = (len(arrays["warm_ids"]), min(12, len(arrays["articles"])))
    predictions = arrays["predictions"]
    if predictions.shape != expected or (
        predictions.size and (predictions.min() < 0 or predictions.max() >= len(arrays["articles"]))
    ):
        raise PipelineError("invalid_model_prediction_shape")
    if predictions.shape[1] > 1 and np.any(np.diff(np.sort(predictions, axis=1), axis=1) == 0):
        raise PipelineError("duplicate_model_predictions")
    for name in ["known_ids", "warm_ids", "articles"]:
        values = arrays[name]
        if len(values) > 1 and not np.all(values[:-1] < values[1:]):
            raise PipelineError("model_ids_not_unique_sorted")
    if (
        len(arrays["known_ids"]) != manifest["known_customers"]
        or len(arrays["warm_ids"]) != manifest["warm_customers"]
        or len(arrays["articles"]) != manifest["candidate_count"]
    ):
        raise PipelineError("model_population_count_mismatch")
    pop = arrays["popularity"]
    if (
        pop.shape != (expected[1],)
        or len(np.unique(pop)) != len(pop)
        or (pop.size and (pop.min() < 0 or pop.max() >= len(arrays["articles"])))
    ):
        raise PipelineError("invalid_model_fallback")
    return {"model_id": model_id, "manifest": manifest, "arrays": arrays}


def load_registered_model(conn, work_dir, model_id):
    model = load_model(work_dir, model_id)
    row = conn.execute(
        "SELECT status,cutoff_date,family FROM control.models WHERE model_id=%s", (model_id,)
    ).fetchone()
    if (
        row is None
        or row[0] != "complete"
        or row[1].isoformat() != model["manifest"]["cutoff"]
        or row[2] != model["manifest"]["family"]
    ):
        raise PipelineError("complete_registered_model_required")
    return model


def recommend(model, customer, k=12):
    if not 1 <= k <= 12:
        raise PipelineError("k_must_be_between_1_and_12")
    from hm_menswear.validation.values import CUSTOMER

    if not CUSTOMER.fullmatch(customer):
        raise PipelineError("invalid_customer_identifier")
    arrays = model["arrays"]
    token = customer.encode("ascii")
    index = int(np.searchsorted(arrays["warm_ids"], token))
    if index < len(arrays["warm_ids"]) and arrays["warm_ids"][index] == token:
        chosen = arrays["predictions"][index]
        reason = (
            "recent_popularity"
            if model["manifest"]["family"] == "popularity"
            else model["manifest"]["family"]
        )
    else:
        chosen = arrays["popularity"]
        index = int(np.searchsorted(arrays["known_ids"], token))
        reason = (
            "no_menswear_history"
            if index < len(arrays["known_ids"]) and arrays["known_ids"][index] == token
            else "unobserved_customer"
        )
    if not len(chosen):
        reason = "no_candidates"
    return {
        "model_id": model["model_id"],
        "cutoff": model["manifest"]["cutoff"],
        "articles": [value.decode("ascii") for value in arrays["articles"][chosen[:k]]],
        "strategy": reason,
    }
