"""Research artifact registry: metadata in git, bytes nowhere near it.

A trained model is never committed. What is committed is a JSON record under
``artifacts/research/<artifact_id>/metadata.json`` that says exactly how to
re-derive and verify the artifact: which dataset hash it was trained on, under
which licence evidence, with which config, at which code commit, evaluated by
which chronological splits, producing which metrics, and which local file
(checksummed) holds the weights.

Rules this module enforces rather than documents:

* Every record is ``research_only: true`` and ``production_approved: false``.
  A record claiming production approval is rejected, not downgraded, because a
  silent downgrade would hide a caller that believes it is shipping.
* ``provenance.eligibility.production_eligible`` must be exactly ``False``. The
  string ``"false"``, ``None`` and ``0`` are all rejected: only a Boolean is a
  statement, and only ``False`` is true here.
* Referenced artifact files must live under the gitignored ``data/`` directory,
  and their *resolved* paths must stay beneath the resolved data root, so a
  symlink cannot point at tracked source or outside the repository.
* The artifact id is recomputed from family, dataset hash and config hash during
  validation. A record cannot name itself.
* Registration is immutable: an existing id cannot be rewritten with different
  metadata, so history cannot be edited after the fact.
* Splits must be chronological: every training season precedes its test season.

Separation from production: :class:`ProductionArtifactRegistry` exists only to
refuse. There is no production path yet, and no code here may pretend otherwise.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from datetime import datetime

ARTIFACT_SCHEMA_VERSION = "rsil-artifact-v1"
REGISTRY_ROOT = os.path.join("artifacts", "research")

#: Only this tree may hold referenced artifact files. It is gitignored.
DATA_DIR = "data"

#: Tracked directories. A referenced file must never resolve into one of these.
TRACKED_PREFIXES = ("src/", "tests/", "docs/", ".github/", "artifacts/", "scripts/")

#: Extensions allowed for a *referenced* (locally retained) artifact file.
ARTIFACT_FILE_SUFFIXES = (".json", ".npz", ".pkl", ".joblib", ".parquet", ".csv")

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_SEASON = re.compile(r"^(\d{4})(?:-(\d{2}|\d{4}))?$")
_DRIVE = re.compile(r"^[A-Za-z]:")
_ARTIFACT_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,80}$")

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

DATASET_KEYS = {"manifest_hash", "corpus_version", "schema_version", "partitions"}
PROVENANCE_KEYS = {"sources", "eligibility", "notes"}
SOURCE_KEYS = {"provider", "repository", "revision", "licence", "licence_reference", "checked_at"}
ELIGIBILITY_KEYS = {"production_eligible", "reason", "gates"}
TRAINING_KEYS = {"config_file", "config_sha256", "hyperparameters", "seasons", "refit"}
EVALUATION_KEYS = {"protocol", "splits", "random_split", "notes"}
SPLIT_KEYS = {"test_season", "train_seasons", "refit"}
METRICS_KEYS = {"log_loss", "brier", "ece", "n", "calibration", "notes"}
CALIBRATION_KEYS = {"bin", "predicted", "observed", "n"}
FILE_KEYS = {"path", "sha256", "bytes"}


class RegistryError(RuntimeError):
    """A record failed validation. ``code`` is stable and machine-readable."""

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


# --------------------------------------------------------------------------- #
# primitives
# --------------------------------------------------------------------------- #

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


def _reject_unknown(block: dict, allowed: set, label: str) -> None:
    unexpected = sorted(set(block) - allowed)
    if unexpected:
        raise RegistryError(f"unexpected:{label}." + ",".join(unexpected),
                            f"{label} carries fields the schema does not define")


def _finite(value, label: str, *, low: float | None = None,
            high: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RegistryError(f"invalid:{label}", f"{label} must be numeric")
    if not math.isfinite(value):
        raise RegistryError("non_finite_metric", f"{label} must be finite, got {value!r}")
    if low is not None and value < low:
        raise RegistryError(f"invalid:{label}", f"{label} below {low}")
    if high is not None and value > high:
        raise RegistryError(f"invalid:{label}", f"{label} above {high}")
    return float(value)


def _positive_int(value, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RegistryError(f"invalid:{label}", f"{label} must be an integer")
    if value <= 0:
        raise RegistryError(f"invalid:{label}", f"{label} must be positive")
    return value


def season_start(season) -> int:
    """Return the start year of a season identifier, or raise.

    Accepts ``2021``, ``2021-22`` and ``2021-2022``. A two-part season must be
    consecutive: ``2021-23`` is malformed, not merely unusual.
    """
    if not isinstance(season, str):
        raise RegistryError("invalid_season", f"season must be a string, got {season!r}")
    match = _SEASON.match(season.strip())
    if not match:
        raise RegistryError("invalid_season", f"malformed season identifier: {season!r}")
    start = int(match.group(1))
    tail = match.group(2)
    if tail:
        end = int(tail) if len(tail) == 4 else 2000 + int(tail) if int(tail) < 100 else int(tail)
        if len(tail) == 2:
            end = (start // 100) * 100 + int(tail)
            if end < start:
                end += 100
        if end != start + 1:
            raise RegistryError("invalid_season",
                                f"season {season!r} spans more than one year")
    return start


# --------------------------------------------------------------------------- #
# identity
# --------------------------------------------------------------------------- #

def artifact_id(model_family: str, dataset_hash: str, config_hash: str) -> str:
    """Deterministic id: same family, dataset and config give the same id."""
    if not isinstance(model_family, str) or not model_family:
        raise RegistryError("invalid:model_family", "model_family is required")
    for label, value in (("dataset_hash", dataset_hash), ("config_hash", config_hash)):
        if not _HEX64.match(str(value or "")):
            raise RegistryError(f"invalid:{label}", f"{label} must be 64 hex characters")
    digest = hashlib.sha256(f"{model_family}|{dataset_hash}|{config_hash}".encode())
    return f"{model_family}-{digest.hexdigest()[:16]}"


# --------------------------------------------------------------------------- #
# paths
# --------------------------------------------------------------------------- #

def _check_path(path: str) -> str:
    """Normalise and bound a referenced file path to ``data/``.

    Rejects absolute paths, Windows drive letters, traversal in either slash
    style, and anything under a tracked directory.
    """
    if not isinstance(path, str) or not path:
        raise RegistryError("invalid:files.path", "each file entry needs a path")
    normalized = path.replace("\\", "/")
    if _DRIVE.match(normalized) or normalized.startswith("/"):
        raise RegistryError("absolute_path", f"path must be relative to the repo: {path}")
    segments = [segment for segment in normalized.split("/") if segment not in ("", ".")]
    if ".." in segments:
        raise RegistryError("path_traversal", f"path may not traverse: {path}")
    joined = "/".join(segments)
    for prefix in TRACKED_PREFIXES:
        if joined.startswith(prefix):
            raise RegistryError(
                "tracked_path_refused",
                f"{path} is inside the tracked tree; weights and datasets stay in data/",
            )
    if not joined.startswith(DATA_DIR + "/"):
        raise RegistryError("outside_data_dir",
                            f"{path} must live under {DATA_DIR}/, the ignored data root")
    if not joined.lower().endswith(ARTIFACT_FILE_SUFFIXES):
        raise RegistryError("invalid:files.path", f"unsupported artifact file type: {path}")
    return joined


def _resolve_under_data(base_dir: str, path: str) -> str:
    """Resolve symlinks and prove the target stays inside the data root."""
    data_root = os.path.realpath(os.path.join(base_dir, DATA_DIR))
    target = os.path.realpath(os.path.join(base_dir, path))
    if target != data_root and not target.startswith(data_root + os.sep):
        raise RegistryError("symlink_escape",
                            f"{path} resolves outside the data root")
    for prefix in TRACKED_PREFIXES:
        tracked = os.path.realpath(os.path.join(base_dir, prefix))
        if target == tracked or target.startswith(tracked + os.sep):
            raise RegistryError("tracked_path_refused",
                                f"{path} resolves into tracked content")
    return target


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --------------------------------------------------------------------------- #
# validation
# --------------------------------------------------------------------------- #

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

    _require_str(record, "model_family")
    _require_str(record, "schema_version")
    _require_str(record, "feature_version")

    # --- dataset -----------------------------------------------------------
    dataset = _require_dict(record, "dataset")
    _reject_unknown(dataset, DATASET_KEYS, "dataset")
    if not _HEX64.match(str(dataset.get("manifest_hash", ""))):
        raise RegistryError("invalid:dataset.manifest_hash",
                            "manifest_hash must be 64 hex characters")
    if not isinstance(dataset.get("corpus_version"), str) or not dataset["corpus_version"]:
        raise RegistryError("missing:dataset.corpus_version", "corpus_version is required")

    # --- provenance --------------------------------------------------------
    provenance = _require_dict(record, "provenance")
    _reject_unknown(provenance, PROVENANCE_KEYS, "provenance")
    sources = provenance.get("sources")
    if not isinstance(sources, list) or not sources:
        raise RegistryError("missing:provenance.sources",
                            "at least one source reference is required")
    for source in sources:
        if not isinstance(source, dict):
            raise RegistryError("invalid:provenance.sources", "each source must be an object")
        _reject_unknown(source, SOURCE_KEYS, "provenance.sources")
        provider = source.get("provider")
        if not isinstance(provider, str) or not provider:
            raise RegistryError("invalid:provenance.sources", "each source needs a provider")
        licence = source.get("licence")
        reference = source.get("licence_reference")
        if not (isinstance(licence, str) and licence) and not (
                isinstance(reference, str) and reference):
            raise RegistryError("missing:provenance.licence",
                                f"source {provider} has no licence reference")
        revision = source.get("revision")
        if revision is not None and not _HEX40.match(str(revision)):
            raise RegistryError("invalid:provenance.sources.revision",
                                f"source {provider} revision must be a 40-character SHA")

    eligibility = provenance.get("eligibility")
    if not isinstance(eligibility, dict):
        raise RegistryError("missing:provenance.eligibility",
                            "record must state the dataset's production eligibility")
    _reject_unknown(eligibility, ELIGIBILITY_KEYS, "provenance.eligibility")
    if "production_eligible" not in eligibility:
        raise RegistryError("missing:provenance.eligibility.production_eligible",
                            "eligibility must be stated explicitly")
    eligible = eligibility["production_eligible"]
    if not isinstance(eligible, bool) or eligible is not False:
        raise RegistryError(
            "production_eligibility_must_be_false",
            "production_eligible must be the Boolean false; this registry cannot "
            "mark a dataset production eligible",
        )

    # --- training ----------------------------------------------------------
    training = _require_dict(record, "training")
    _reject_unknown(training, TRAINING_KEYS, "training")
    if not _HEX64.match(str(training.get("config_sha256", ""))):
        raise RegistryError("invalid:training.config_sha256",
                            "config_sha256 must be 64 hex characters")
    if not isinstance(training.get("hyperparameters"), dict) or not training["hyperparameters"]:
        raise RegistryError("missing:training.hyperparameters",
                            "hyperparameters must be recorded, not implied")
    seasons = training.get("seasons")
    if seasons is not None:
        if not isinstance(seasons, list) or not seasons:
            raise RegistryError("invalid:training.seasons", "seasons must be a non-empty list")
        for season in seasons:
            season_start(season)

    # --- identity is recomputed, never trusted ----------------------------
    expected_id = artifact_id(record["model_family"], dataset["manifest_hash"],
                              training["config_sha256"])
    if record.get("artifact_id") != expected_id:
        raise RegistryError(
            "artifact_id_mismatch",
            f"artifact_id must be {expected_id}, got {record.get('artifact_id')!r}",
        )

    if not _HEX40.match(str(record.get("code_commit", ""))):
        raise RegistryError("invalid:code_commit",
                            "code_commit must be a full 40-character SHA")

    # --- evaluation --------------------------------------------------------
    evaluation = _require_dict(record, "evaluation")
    _reject_unknown(evaluation, EVALUATION_KEYS, "evaluation")
    if evaluation.get("protocol") != "walk_forward":
        raise RegistryError("invalid:evaluation.protocol",
                            "only walk_forward evaluation is accepted")
    splits = evaluation.get("splits")
    if not isinstance(splits, list) or not splits:
        raise RegistryError("missing:evaluation.splits",
                            "chronological split definitions are required")
    for split in splits:
        if not isinstance(split, dict):
            raise RegistryError("invalid:evaluation.splits", "each split must be an object")
        _reject_unknown(split, SPLIT_KEYS, "evaluation.splits")
        test_season = split.get("test_season")
        if test_season is None:
            raise RegistryError("invalid:evaluation.splits", "each split needs a test_season")
        test_start = season_start(test_season)
        train_seasons = split.get("train_seasons")
        if not isinstance(train_seasons, list) or not train_seasons:
            raise RegistryError("invalid:evaluation.splits",
                                "each split needs train_seasons")
        for season in train_seasons:
            if season_start(season) >= test_start:
                raise RegistryError(
                    "season_order_invalid",
                    f"training season {season!r} does not precede test season "
                    f"{test_season!r}",
                )
    if evaluation.get("random_split") not in (None, False):
        raise RegistryError("invalid:evaluation.random_split",
                            "random splitting is not permitted")

    # --- metrics -----------------------------------------------------------
    metrics = _require_dict(record, "metrics")
    _reject_unknown(metrics, METRICS_KEYS, "metrics")
    _finite(metrics.get("log_loss"), "metrics.log_loss", low=0.0)
    _finite(metrics.get("brier"), "metrics.brier", low=0.0, high=2.0)
    _finite(metrics.get("ece"), "metrics.ece", low=0.0, high=1.0)
    _positive_int(metrics.get("n"), "metrics.n")
    calibration = metrics.get("calibration")
    if not isinstance(calibration, list) or not calibration:
        raise RegistryError("missing:metrics.calibration",
                            "calibration results are required")
    for bucket in calibration:
        if not isinstance(bucket, dict):
            raise RegistryError("invalid:metrics.calibration",
                                "each calibration bucket must be an object")
        _reject_unknown(bucket, CALIBRATION_KEYS, "metrics.calibration")
        _finite(bucket.get("bin"), "metrics.calibration.bin", low=0.0, high=1.0)
        _finite(bucket.get("observed"), "metrics.calibration.observed", low=0.0, high=1.0)
        if "predicted" in bucket:
            _finite(bucket["predicted"], "metrics.calibration.predicted", low=0.0, high=1.0)
        _positive_int(bucket.get("n"), "metrics.calibration.n")

    created = _require_str(record, "created_at")
    if not created.endswith("Z"):
        raise RegistryError("invalid:created_at", "created_at must be UTC (Z)")
    try:
        datetime.fromisoformat(created.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RegistryError("invalid:created_at", str(exc)) from exc

    # --- files -------------------------------------------------------------
    files = record["files"]
    if files and verify_files and not base_dir:
        raise RegistryError(
            "base_dir_required",
            "file verification was requested and files are referenced, so base_dir "
            "is required; skipping verification silently is not allowed",
        )
    seen = set()
    for entry in files:
        if not isinstance(entry, dict):
            raise RegistryError("invalid:files", "each file entry must be an object")
        _reject_unknown(entry, FILE_KEYS, "files")
        path = _check_path(entry.get("path", ""))
        if path in seen:
            raise RegistryError("invalid:files", f"duplicate file entry: {path}")
        seen.add(path)
        if not _HEX64.match(str(entry.get("sha256", ""))):
            raise RegistryError("invalid:files.sha256",
                                f"sha256 missing or malformed for {path}")
        if "bytes" in entry:
            _positive_int(entry["bytes"], "files.bytes")
        if verify_files and base_dir:
            target = _resolve_under_data(base_dir, path)
            if not os.path.isfile(target):
                raise RegistryError("file_missing", f"referenced file not found: {path}")
            if _sha256_file(target) != entry["sha256"]:
                raise RegistryError("checksum_mismatch", f"checksum differs for {path}")

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


# --------------------------------------------------------------------------- #
# storage
# --------------------------------------------------------------------------- #

def record_dir(artifact_id_value: str, root: str = REGISTRY_ROOT) -> str:
    if not _ARTIFACT_ID.match(str(artifact_id_value or "")):
        raise RegistryError("invalid:artifact_id",
                            "artifact_id must be a lowercase slug")
    return os.path.join(root, artifact_id_value)


def _canonical(record: dict) -> str:
    return json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + "\n"


def write_record(record: dict, *, root: str = REGISTRY_ROOT,
                 base_dir: str | None = None, verify_files: bool = True) -> str:
    """Validate, then write ``metadata.json`` once. Registration is immutable."""
    validate(record, base_dir=base_dir, verify_files=verify_files)
    directory = record_dir(record["artifact_id"], root)
    os.makedirs(directory, exist_ok=True)
    target = os.path.join(directory, "metadata.json")
    payload = _canonical(record)
    if os.path.exists(target):
        existing = load_record(target)
        if _canonical(existing) == payload:
            return target
        raise RegistryError(
            "artifact_immutable",
            f"{record['artifact_id']} is already registered with different metadata; "
            "a new dataset or config means a new id, not an edited record",
        )
    handle, temp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(temp, target)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return target


def _reject_constant(token: str):
    raise RegistryError("invalid:json", f"non-finite JSON value not permitted: {token}")


def load_record(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh, parse_constant=_reject_constant)


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
