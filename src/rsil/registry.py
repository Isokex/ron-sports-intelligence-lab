"""Research artifact registry: metadata in git, bytes nowhere near it.

A trained model is never committed. What is committed is a JSON record under
``artifacts/research/<artifact_id>/metadata.json`` that says exactly how to
re-derive and verify the artifact: which dataset hash it was trained on, under
which licence evidence, with which config, at which code commit, evaluated by
which chronological splits, producing which metrics, and which local file
(checksummed) holds the weights.

Two rules are enforced by this module rather than merely documented:

* Every record is ``research_only: true`` and ``production_approved: false``.
  A record claiming production approval is rejected, not downgraded, because a
  silent downgrade would hide a caller that believes it is shipping.
* A record may not point at a file inside the tracked source tree. Weights and
  datasets live outside the repository (``data/``, gitignored); a record that
  references ``src/`` or ``artifacts/`` is either a mistake or an attempt to
  smuggle a binary into git.

Separation from production: :class:`ProductionArtifactRegistry` exists only to
refuse. There is no production path yet, and no code in this repository may
pretend otherwise.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime

ARTIFACT_SCHEMA_VERSION = "rsil-artifact-v1"
REGISTRY_ROOT = os.path.join("artifacts", "research")

#: Directories that are tracked by git. A referenced file must never resolve here.
TRACKED_PREFIXES = ("src/", "tests/", "docs/", ".github/", "artifacts/", "scripts/")

#: Extensions allowed for a *referenced* (locally retained) artifact file.
ARTIFACT_FILE_SUFFIXES = (".json", ".npz", ".pkl", ".joblib", ".parquet", ".csv")

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_SHA1_OR_SHA256 = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")

REQUIRED = (
    "artifact_id",
    "artifact_schema",
    "model_family",
    "dataset",
    "provenance",
    "schema_version",
    "feature_version",
    "training",
    "code_commit",
    "evaluation",
    "metrics",
    "created_at",
    "files",
    "research_only",
    "production_approved",
)


class RegistryError(RuntimeError):
    """A record failed validation. ``code`` is stable and machine-readable."""

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


def _require(record: dict, key: str) -> object:
    if key not in record or record[key] in (None, "", [], {}):
        raise RegistryError(f"missing:{key}", f"{key} is required")
    return record[key]


def _require_str(record: dict, key: str) -> str:
    value = _require(record, key)
    if not isinstance(value, str):
        raise RegistryError(f"invalid:{key}", f"{key} must be a string")
    return value


def _require_dict(record: dict, key: str) -> dict:
    value = _require(record, key)
    if not isinstance(value, dict):
        raise RegistryError(f"invalid:{key}", f"{key} must be an object")
    return value


def artifact_id(model_family: str, dataset_hash: str, config_hash: str) -> str:
    """Deterministic id: same family, dataset and config give the same id."""
    if not model_family:
        raise RegistryError("invalid:model_family", "model_family is required")
    for label, value in (("dataset_hash", dataset_hash), ("config_hash", config_hash)):
        if not _HEX64.match(str(value or "")):
            raise RegistryError(f"invalid:{label}", f"{label} must be 64 hex characters")
    digest = hashlib.sha256(f"{model_family}|{dataset_hash}|{config_hash}".encode())
    return f"{model_family}-{digest.hexdigest()[:16]}"


def _check_path(path: str) -> str:
    if not isinstance(path, str) or not path:
        raise RegistryError("invalid:files.path", "each file entry needs a path")
    normalized = path.replace("\\", "/")
    if normalized.startswith("/") or ".." in normalized.split("/"):
        raise RegistryError("invalid:files.path", f"path must be relative: {path}")
    for prefix in TRACKED_PREFIXES:
        if normalized.startswith(prefix):
            raise RegistryError(
                "tracked_path_refused",
                f"{path} is inside the tracked tree; weights and datasets stay in data/",
            )
    if not normalized.lower().endswith(ARTIFACT_FILE_SUFFIXES):
        raise RegistryError(
            "invalid:files.path", f"unsupported artifact file type: {path}"
        )
    return normalized


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate(record: dict, *, base_dir: str | None = None,
             verify_files: bool = True) -> dict:
    """Validate a record and return it unchanged.

    Missing metadata raises; it never degrades to a warning, because a record
    that passes validation is later treated as evidence.
    """
    if not isinstance(record, dict):
        raise RegistryError("invalid:record", "record must be an object")

    for key in REQUIRED:
        if key == "files":
            # An empty list is legitimate: metadata-only records that retain no
            # local weights still carry provenance and evaluation evidence.
            if "files" not in record:
                raise RegistryError("missing:files", "files is required")
            if not isinstance(record["files"], list):
                raise RegistryError("invalid:files", "files must be a list (may be empty)")
            continue
        _require(record, key)

    unexpected = sorted(set(record) - set(REQUIRED))
    if unexpected:
        raise RegistryError("unexpected:" + ",".join(unexpected),
                            "record carries fields the schema does not define")

    if record["artifact_schema"] != ARTIFACT_SCHEMA_VERSION:
        raise RegistryError(
            "invalid:artifact_schema",
            f"expected {ARTIFACT_SCHEMA_VERSION}, got {record['artifact_schema']}",
        )

    _require_str(record, "artifact_id")
    _require_str(record, "model_family")
    _require_str(record, "schema_version")
    _require_str(record, "feature_version")

    dataset = _require_dict(record, "dataset")
    if not _HEX64.match(str(dataset.get("manifest_hash", ""))):
        raise RegistryError("invalid:dataset.manifest_hash",
                            "manifest_hash must be 64 hex characters")
    if not dataset.get("corpus_version"):
        raise RegistryError("missing:dataset.corpus_version",
                            "corpus_version is required")

    provenance = _require_dict(record, "provenance")
    sources = provenance.get("sources")
    if not isinstance(sources, list) or not sources:
        raise RegistryError("missing:provenance.sources",
                            "at least one source reference is required")
    for source in sources:
        if not isinstance(source, dict) or not source.get("provider"):
            raise RegistryError("invalid:provenance.sources",
                                "each source needs a provider")
        if not (source.get("licence") or source.get("licence_reference")):
            raise RegistryError("missing:provenance.licence",
                                f"source {source.get('provider')} has no licence reference")
    eligibility = provenance.get("eligibility")
    if not isinstance(eligibility, dict) or "production_eligible" not in eligibility:
        raise RegistryError(
            "missing:provenance.eligibility",
            "record must state the dataset's production eligibility",
        )

    training = _require_dict(record, "training")
    if not _HEX64.match(str(training.get("config_sha256", ""))):
        raise RegistryError("invalid:training.config_sha256",
                            "config_sha256 must be 64 hex characters")
    if not isinstance(training.get("hyperparameters"), dict) or not training["hyperparameters"]:
        raise RegistryError("missing:training.hyperparameters",
                            "hyperparameters must be recorded, not implied")

    if not _HEX40.match(str(record.get("code_commit", ""))):
        raise RegistryError("invalid:code_commit",
                            "code_commit must be a full 40-character SHA")

    evaluation = _require_dict(record, "evaluation")
    if evaluation.get("protocol") != "walk_forward":
        raise RegistryError("invalid:evaluation.protocol",
                            "only walk_forward evaluation is accepted")
    splits = evaluation.get("splits")
    if not isinstance(splits, list) or not splits:
        raise RegistryError("missing:evaluation.splits",
                            "chronological split definitions are required")
    for split in splits:
        if not isinstance(split, dict) or not split.get("test_season"):
            raise RegistryError("invalid:evaluation.splits",
                                "each split needs a test_season")
        if not isinstance(split.get("train_seasons"), list) or not split["train_seasons"]:
            raise RegistryError("invalid:evaluation.splits",
                                "each split needs train_seasons")
    if evaluation.get("random_split") not in (None, False):
        raise RegistryError("invalid:evaluation.random_split",
                            "random splitting is not permitted")

    metrics = _require_dict(record, "metrics")
    for key in ("log_loss", "brier", "ece"):
        value = metrics.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise RegistryError(f"missing:metrics.{key}", f"{key} must be numeric")
    n = metrics.get("n")
    if not isinstance(n, int) or isinstance(n, bool) or n <= 0:
        raise RegistryError("invalid:metrics.n", "n must be a positive integer")
    calibration = metrics.get("calibration")
    if not isinstance(calibration, list) or not calibration:
        raise RegistryError("missing:metrics.calibration",
                            "calibration results are required")
    for bucket in calibration:
        if not isinstance(bucket, dict) or "bin" not in bucket or "observed" not in bucket:
            raise RegistryError("invalid:metrics.calibration",
                                "each calibration bucket needs bin and observed")

    created = _require_str(record, "created_at")
    if not created.endswith("Z"):
        raise RegistryError("invalid:created_at", "created_at must be UTC (Z)")
    try:
        datetime.fromisoformat(created.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RegistryError("invalid:created_at", str(exc)) from exc

    files = record.get("files")
    if not isinstance(files, list):
        raise RegistryError("invalid:files", "files must be a list (may be empty)")
    seen = set()
    for entry in files:
        if not isinstance(entry, dict):
            raise RegistryError("invalid:files", "each file entry must be an object")
        path = _check_path(entry.get("path", ""))
        if path in seen:
            raise RegistryError("invalid:files", f"duplicate file entry: {path}")
        seen.add(path)
        if not _HEX64.match(str(entry.get("sha256", ""))):
            raise RegistryError("invalid:files.sha256",
                                f"sha256 missing or malformed for {path}")
        if verify_files and base_dir:
            absolute = os.path.join(base_dir, path)
            if not os.path.isfile(absolute):
                raise RegistryError("file_missing", f"referenced file not found: {path}")
            if _sha256_file(absolute) != entry["sha256"]:
                raise RegistryError("checksum_mismatch",
                                    f"checksum differs for {path}")

    if record["research_only"] is not True:
        raise RegistryError("research_only_required",
                            "research artifacts must declare research_only: true")
    if record["production_approved"] is not False:
        raise RegistryError(
            "production_approval_not_supported",
            "this registry cannot approve production use; production artifacts need a "
            "separate mechanism and explicit human approval",
        )
    return record


def build_record(*, model_family: str, dataset: dict, provenance: dict,
                 schema_version: str, feature_version: str, training: dict,
                 code_commit: str, evaluation: dict, metrics: dict,
                 created_at: str, files: list) -> dict:
    """Assemble a record with the id derived from family, dataset and config."""
    config_sha = (training or {}).get("config_sha256", "")
    record = {
        "artifact_id": artifact_id(model_family, (dataset or {}).get("manifest_hash", ""),
                                   config_sha),
        "artifact_schema": ARTIFACT_SCHEMA_VERSION,
        "model_family": model_family,
        "dataset": dataset,
        "provenance": provenance,
        "schema_version": schema_version,
        "feature_version": feature_version,
        "training": training,
        "code_commit": code_commit,
        "evaluation": evaluation,
        "metrics": metrics,
        "created_at": created_at,
        "files": files,
        "research_only": True,
        "production_approved": False,
    }
    return validate(record, verify_files=False)


def record_dir(artifact_id_value: str, root: str = REGISTRY_ROOT) -> str:
    if not re.match(r"^[a-z0-9][a-z0-9._-]{0,80}$", str(artifact_id_value or "")):
        raise RegistryError("invalid:artifact_id",
                            "artifact_id must be a lowercase slug")
    return os.path.join(root, artifact_id_value)


def write_record(record: dict, *, root: str = REGISTRY_ROOT,
                 base_dir: str | None = None, verify_files: bool = True) -> str:
    """Validate, then write ``metadata.json``. Only that one file is written."""
    validate(record, base_dir=base_dir, verify_files=verify_files)
    directory = record_dir(record["artifact_id"], root)
    os.makedirs(directory, exist_ok=True)
    target = os.path.join(directory, "metadata.json")
    payload = json.dumps(record, indent=2, sort_keys=True) + "\n"
    handle, temp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(temp, target)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return target


def load_record(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def assert_metadata_only(root: str = REGISTRY_ROOT) -> None:
    """Fail if anything other than metadata.json exists in the registry tree."""
    if not os.path.isdir(root):
        return
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if name != "metadata.json":
                raise RegistryError(
                    "non_metadata_file",
                    f"{os.path.join(dirpath, name)} is not metadata; weights and "
                    "datasets do not belong in the repository",
                )


class ProductionArtifactRegistry:
    """Placeholder for a future approved mechanism. Refuses every operation.

    Kept separate on purpose: nothing in the research path can reach production
    approval by adding a field or flipping a flag.
    """

    CODE = "production_registry_not_available"

    def register(self, *_args, **_kwargs):
        raise RegistryError(self.CODE, "no production artifact mechanism exists yet")

    def load(self, *_args, **_kwargs):
        raise RegistryError(self.CODE, "no production artifact mechanism exists yet")
