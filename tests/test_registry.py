"""Artifact registry tests.

Each test names the failure it prevents. The registry is governance code: a
record that validates is later treated as evidence, so every "should fail" case
here is a way a research model could otherwise drift toward production, or a way
a record could misdescribe what it was trained on.
"""
import hashlib
import json
import os

import pytest

from rsil import registry


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


DATASET_HASH = sha("corpus-v1")
CONFIG_HASH = sha("config")


def base_record(**overrides) -> dict:
    record = {
        "artifact_id": registry.artifact_id("dixon-coles", DATASET_HASH, CONFIG_HASH),
        "artifact_schema": registry.ARTIFACT_SCHEMA_VERSION,
        "model_family": "dixon-coles",
        "dataset": {
            "manifest_hash": DATASET_HASH,
            "corpus_version": "openfootball-2024-25-v1",
            "schema_version": "rsil-match-v2",
        },
        "provenance": {
            "sources": [{
                "provider": "openfootball",
                "repository": "openfootball/football.json",
                "revision": "0" * 40,
                "licence": "CC0-1.0",
                "licence_reference": "docs/phase-2a-licensing-assessment.md#4.2",
                "checked_at": "2026-11-25",
            }],
            "eligibility": {
                "production_eligible": False,
                "reason": "research-only corpus, gates 2-4 unmet",
            },
        },
        "schema_version": "rsil-match-v2",
        "feature_version": "features-v1",
        "training": {
            "config_file": "data/config/dixon-coles-v1.yaml",
            "config_sha256": CONFIG_HASH,
            "hyperparameters": {"xi": 0.0019, "rho_bounds": [-0.2, 0.2]},
            "seasons": ["2019-20", "2020-21"],
        },
        "code_commit": "a" * 40,
        "evaluation": {
            "protocol": "walk_forward",
            "random_split": False,
            "splits": [{"test_season": "2021-22", "train_seasons": ["2019-20", "2020-21"]}],
        },
        "metrics": {
            "log_loss": 0.98,
            "brier": 0.62,
            "ece": 0.03,
            "n": 380,
            "calibration": [{"bin": 0.1, "predicted": 0.1, "observed": 0.12, "n": 41}],
        },
        "created_at": "2026-11-25T00:00:00Z",
        "files": [{"path": "data/artifacts/dixon-coles-v1/params.json",
                   "sha256": sha("weights"), "bytes": 12}],
        "research_only": True,
        "production_approved": False,
    }
    record.update(overrides)
    return record


def check(record, **kwargs):
    kwargs.setdefault("verify_files", False)
    return registry.validate(record, **kwargs)


def error_code(record, **kwargs) -> str:
    with pytest.raises(registry.RegistryError) as exc:
        check(record, **kwargs)
    return exc.value.code


# --------------------------------------------------------------------------- #
# baseline
# --------------------------------------------------------------------------- #

def test_valid_record_passes():
    assert check(base_record())["research_only"] is True


@pytest.mark.parametrize("field", ["dataset", "provenance", "training", "evaluation",
                                   "metrics", "code_commit", "created_at", "files",
                                   "artifact_id", "model_family"])
def test_missing_required_block_fails(field):
    record = base_record()
    del record[field]
    assert error_code(record).startswith(("missing:", "invalid:"))


def test_unknown_top_level_field_is_refused():
    assert error_code(base_record(production_ready=True)).startswith("unexpected:")


def test_research_only_false_fails():
    assert error_code(base_record(research_only=False)) == "research_only_required"


def test_production_approval_is_refused_not_downgraded():
    assert error_code(base_record(production_approved=True)) == (
        "production_approval_not_supported")


# --------------------------------------------------------------------------- #
# 1. production eligibility is a Boolean false or nothing
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("value", [True, None, "false", "False", 0, 1, "", [], {}])
def test_production_eligible_must_be_boolean_false(value):
    record = base_record()
    record["provenance"]["eligibility"]["production_eligible"] = value
    assert error_code(record) == "production_eligibility_must_be_false"


def test_missing_production_eligible_fails():
    record = base_record()
    del record["provenance"]["eligibility"]["production_eligible"]
    assert error_code(record) == "missing:provenance.eligibility.production_eligible"


def test_missing_eligibility_block_fails():
    record = base_record()
    del record["provenance"]["eligibility"]
    assert error_code(record) == "missing:provenance.eligibility"


def test_eligibility_unknown_key_is_refused():
    record = base_record()
    record["provenance"]["eligibility"]["approved_by_ceo"] = True
    assert error_code(record).startswith("unexpected:provenance.eligibility")


def test_missing_licence_reference_fails():
    record = base_record()
    del record["provenance"]["sources"][0]["licence_reference"]
    del record["provenance"]["sources"][0]["licence"]
    assert error_code(record) == "missing:provenance.licence"


def test_source_revision_must_be_full_sha():
    record = base_record()
    record["provenance"]["sources"][0]["revision"] = "abc123"
    assert error_code(record) == "invalid:provenance.sources.revision"


# --------------------------------------------------------------------------- #
# 2 and 3. file references stay under data/, in either slash style
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("path,code", [
    ("weights.pkl", "outside_data_dir"),
    ("artifacts/research/x/weights.pkl", "tracked_path_refused"),
    ("src/rsil/registry.py", "tracked_path_refused"),
    ("tests/test_registry.py", "tracked_path_refused"),
    ("docs/corpus.md", "tracked_path_refused"),
    ("data/../src/rsil/weights.json", "path_traversal"),
    ("data\\..\\..\\src\\weights.json", "path_traversal"),
    ("..\\..\\weights.json", "path_traversal"),
    ("/etc/passwd", "absolute_path"),
    ("C:\\Users\\weights.json", "absolute_path"),
    ("data/weights.exe", "invalid:files.path"),
])
def test_file_reference_must_stay_in_data(path, code):
    record = base_record()
    record["files"] = [{"path": path, "sha256": sha("x")}]
    assert error_code(record) == code


def test_duplicate_file_entries_are_refused():
    record = base_record()
    entry = record["files"][0]
    record["files"] = [entry, dict(entry)]
    assert error_code(record) == "invalid:files"


def test_symlink_escape_from_data_is_refused(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "weights.json"
    target.write_text("weights")
    data = tmp_path / "data"
    data.mkdir()
    link = data / "link.json"
    os.symlink(target, link)

    record = base_record()
    record["files"] = [{"path": "data/link.json",
                        "sha256": hashlib.sha256(b"weights").hexdigest()}]
    with pytest.raises(registry.RegistryError) as exc:
        registry.validate(record, base_dir=str(tmp_path), verify_files=True)
    assert exc.value.code == "symlink_escape"


def test_symlink_into_tracked_content_is_refused(tmp_path):
    tracked = tmp_path / "src"
    tracked.mkdir()
    source = tracked / "model.py"
    source.write_text("weights")
    data = tmp_path / "data"
    data.mkdir()
    os.symlink(source, data / "link.json")

    record = base_record()
    record["files"] = [{"path": "data/link.json",
                        "sha256": hashlib.sha256(b"weights").hexdigest()}]
    with pytest.raises(registry.RegistryError) as exc:
        registry.validate(record, base_dir=str(tmp_path), verify_files=True)
    assert exc.value.code in ("symlink_escape", "tracked_path_refused")


# --------------------------------------------------------------------------- #
# 3. identity is recomputed, not trusted
# --------------------------------------------------------------------------- #

def test_correct_artifact_id_passes():
    assert check(base_record())["artifact_id"].startswith("dixon-coles-")


def test_incorrect_artifact_id_fails():
    record = base_record(artifact_id="dixon-coles-ffffffffffffffff")
    assert error_code(record) == "artifact_id_mismatch"


def test_artifact_id_must_track_the_dataset_hash():
    record = base_record()
    record["dataset"]["manifest_hash"] = sha("other-corpus")
    assert error_code(record) == "artifact_id_mismatch"


def test_artifact_id_must_track_the_config_hash():
    record = base_record()
    record["training"]["config_sha256"] = sha("other-config")
    assert error_code(record) == "artifact_id_mismatch"


def test_artifact_id_is_deterministic_and_sensitive():
    first = registry.artifact_id("dixon-coles", sha("a"), sha("b"))
    again = registry.artifact_id("dixon-coles", sha("a"), sha("b"))
    other = registry.artifact_id("dixon-coles", sha("c"), sha("b"))
    assert first == again and first != other


# --------------------------------------------------------------------------- #
# 4. registration is immutable
# --------------------------------------------------------------------------- #

def test_identical_write_is_idempotent(tmp_path):
    root = str(tmp_path / "artifacts/research")
    record = base_record(files=[])
    first = registry.write_record(record, root=root, verify_files=False)
    second = registry.write_record(record, root=root, verify_files=False)
    assert first == second
    assert json.load(open(first))["artifact_id"] == record["artifact_id"]


def test_overwrite_with_different_metadata_is_refused(tmp_path):
    root = str(tmp_path / "artifacts/research")
    record = base_record(files=[])
    registry.write_record(record, root=root, verify_files=False)
    changed = json.loads(json.dumps(record))
    changed["metrics"]["log_loss"] = 0.5
    with pytest.raises(registry.RegistryError) as exc:
        registry.write_record(changed, root=root, verify_files=False)
    assert exc.value.code == "artifact_immutable"


def test_write_leaves_only_metadata(tmp_path):
    root = str(tmp_path / "artifacts/research")
    path = registry.write_record(base_record(files=[]), root=root, verify_files=False)
    assert os.path.basename(path) == "metadata.json"
    registry.assert_metadata_only(root)


def test_non_metadata_file_in_registry_is_detected(tmp_path):
    root = tmp_path / "artifacts/research/dixon-coles-0123456789abcdef"
    root.mkdir(parents=True)
    (root / "weights.pkl").write_bytes(b"\x00")
    with pytest.raises(registry.RegistryError) as exc:
        registry.assert_metadata_only(str(tmp_path / "artifacts/research"))
    assert exc.value.code == "non_metadata_file"


def test_artifact_id_slug_required_for_paths():
    with pytest.raises(registry.RegistryError):
        registry.record_dir("../escape")


# --------------------------------------------------------------------------- #
# 5. walk-forward chronology
# --------------------------------------------------------------------------- #

def test_valid_chronological_split_passes():
    record = base_record()
    record["evaluation"]["splits"] = [
        {"test_season": "2021-22", "train_seasons": ["2019-20", "2020-21"]},
        {"test_season": "2022-23", "train_seasons": ["2019-20", "2020-21", "2021-22"]},
    ]
    assert check(record)["evaluation"]["splits"]


@pytest.mark.parametrize("train_seasons", [
    ["2022-23"],            # future season
    ["2021-22"],            # same season
    ["2021-22", "2022-23"],  # future seasons mixed in
])
def test_future_season_training_is_refused(train_seasons):
    record = base_record()
    record["evaluation"]["splits"] = [{"test_season": "2021-22",
                                       "train_seasons": train_seasons}]
    assert error_code(record) == "season_order_invalid"


@pytest.mark.parametrize("season", ["21-22", "2021-23", "season-2021", "", "20211"])
def test_malformed_season_identifier_is_refused(season):
    record = base_record()
    record["evaluation"]["splits"] = [{"test_season": "2022-23",
                                       "train_seasons": [season]}]
    assert error_code(record) == "invalid_season"


def test_split_unknown_key_is_refused():
    record = base_record()
    record["evaluation"]["splits"] = [{"test_season": "2021-22",
                                       "train_seasons": ["2020-21"],
                                       "random": True}]
    assert error_code(record).startswith("unexpected:evaluation.splits")


def test_random_split_flag_is_refused():
    record = base_record()
    record["evaluation"]["random_split"] = True
    assert error_code(record) == "invalid:evaluation.random_split"


def test_only_walk_forward_protocol_is_accepted():
    record = base_record()
    record["evaluation"]["protocol"] = "kfold"
    assert error_code(record) == "invalid:evaluation.protocol"


# --------------------------------------------------------------------------- #
# 6. metrics must be finite and well formed
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("field", ["log_loss", "brier", "ece"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_metric_is_refused(field, value):
    record = base_record()
    record["metrics"][field] = value
    assert error_code(record) == "non_finite_metric"


def test_negative_log_loss_is_refused():
    record = base_record()
    record["metrics"]["log_loss"] = -0.1
    assert error_code(record) == "invalid:metrics.log_loss"


def test_ece_above_one_is_refused():
    record = base_record()
    record["metrics"]["ece"] = 1.5
    assert error_code(record) == "invalid:metrics.ece"


def test_sample_size_must_be_positive_integer():
    record = base_record()
    record["metrics"]["n"] = 0
    assert error_code(record) == "invalid:metrics.n"


@pytest.mark.parametrize("key,value,code", [
    ("bin", 1.4, "invalid:metrics.calibration.bin"),
    ("bin", -0.1, "invalid:metrics.calibration.bin"),
    ("observed", 2.0, "invalid:metrics.calibration.observed"),
    ("observed", float("nan"), "non_finite_metric"),
    ("predicted", 1.2, "invalid:metrics.calibration.predicted"),
    ("n", 0, "invalid:metrics.calibration.n"),
])
def test_invalid_calibration_bucket_is_refused(key, value, code):
    record = base_record()
    record["metrics"]["calibration"] = [{"bin": 0.1, "observed": 0.12, "n": 41,
                                         key: value}]
    assert error_code(record) == code


def test_calibration_bucket_unknown_key_is_refused():
    record = base_record()
    record["metrics"]["calibration"] = [{"bin": 0.1, "observed": 0.1, "n": 5,
                                         "confidence": 0.9}]
    assert error_code(record).startswith("unexpected:metrics.calibration")


def test_missing_calibration_fails():
    record = base_record()
    record["metrics"]["calibration"] = []
    assert error_code(record) == "missing:metrics.calibration"


def test_load_record_rejects_non_finite_json(tmp_path):
    path = tmp_path / "metadata.json"
    path.write_text('{"log_loss": NaN}')
    with pytest.raises(registry.RegistryError) as exc:
        registry.load_record(str(path))
    assert exc.value.code == "invalid:json"


def test_write_record_refuses_non_finite_payload(tmp_path):
    record = base_record(files=[])
    record["metrics"]["log_loss"] = float("nan")
    with pytest.raises(registry.RegistryError):
        registry.write_record(record, root=str(tmp_path / "reg"), verify_files=False)


# --------------------------------------------------------------------------- #
# 7. verification cannot be skipped by omission
# --------------------------------------------------------------------------- #

def test_files_without_base_dir_fails():
    with pytest.raises(registry.RegistryError) as exc:
        registry.validate(base_record(), verify_files=True)
    assert exc.value.code == "base_dir_required"


def test_no_files_needs_no_base_dir():
    record = base_record(files=[])
    assert registry.validate(record, verify_files=True)["files"] == []


def test_checksum_mismatch_fails(tmp_path):
    data = tmp_path / "data/artifacts/dixon-coles-v1"
    data.mkdir(parents=True)
    (data / "params.json").write_text("different bytes")
    with pytest.raises(registry.RegistryError) as exc:
        registry.validate(base_record(), base_dir=str(tmp_path), verify_files=True)
    assert exc.value.code == "checksum_mismatch"


def test_missing_file_fails(tmp_path):
    (tmp_path / "data").mkdir()
    with pytest.raises(registry.RegistryError) as exc:
        registry.validate(base_record(), base_dir=str(tmp_path), verify_files=True)
    assert exc.value.code == "file_missing"


def test_checksum_match_passes(tmp_path):
    data = tmp_path / "data/artifacts/dixon-coles-v1"
    data.mkdir(parents=True)
    (data / "params.json").write_text("weights")
    record = base_record()
    record["files"][0]["sha256"] = hashlib.sha256(b"weights").hexdigest()
    assert registry.validate(record, base_dir=str(tmp_path))["files"]


# --------------------------------------------------------------------------- #
# 8. nested blocks reject malformed or misleading shapes
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("key", ["manifest_hash", "corpus_version"])
def test_dataset_block_is_required(key):
    record = base_record()
    del record["dataset"][key]
    assert error_code(record).startswith(("missing:", "invalid:"))


def test_dataset_unknown_key_is_refused():
    record = base_record()
    record["dataset"]["rows"] = 380
    assert error_code(record).startswith("unexpected:dataset")


def test_training_requires_hyperparameters():
    record = base_record()
    record["training"]["hyperparameters"] = {}
    assert error_code(record) == "missing:training.hyperparameters"


def test_training_seasons_are_validated():
    record = base_record()
    record["training"]["seasons"] = ["2021-23"]
    assert error_code(record) == "invalid_season"


def test_provenance_requires_at_least_one_source():
    record = base_record()
    record["provenance"]["sources"] = []
    assert error_code(record) == "missing:provenance.sources"


def test_created_at_must_be_utc():
    assert error_code(base_record(created_at="2026-11-25T00:00:00+01:00")) == (
        "invalid:created_at")


def test_code_commit_must_be_full_sha():
    assert error_code(base_record(code_commit="abc1234")) == "invalid:code_commit"


def test_build_record_sets_research_flags_and_derived_id():
    record = registry.build_record(
        model_family="elo",
        dataset={"manifest_hash": sha("corpus"), "corpus_version": "v1"},
        provenance=base_record()["provenance"],
        schema_version="rsil-match-v2",
        feature_version="features-v1",
        training={"config_sha256": sha("cfg"), "hyperparameters": {"K": 20}},
        code_commit="b" * 40,
        evaluation={"protocol": "walk_forward",
                    "splits": [{"test_season": "2022-23", "train_seasons": ["2021-22"]}]},
        metrics={"log_loss": 1.0, "brier": 0.6, "ece": 0.05, "n": 10,
                 "calibration": [{"bin": 0.5, "observed": 0.5, "n": 10}]},
        created_at="2026-11-25T00:00:00Z",
        files=[],
    )
    assert record["research_only"] is True
    assert record["production_approved"] is False
    assert record["artifact_id"] == registry.artifact_id("elo", sha("corpus"), sha("cfg"))


# --------------------------------------------------------------------------- #
# separation from production
# --------------------------------------------------------------------------- #

def test_production_registry_refuses_everything():
    production = registry.ProductionArtifactRegistry()
    with pytest.raises(registry.RegistryError) as exc:
        production.register(base_record())
    assert exc.value.code == "production_registry_not_available"
    with pytest.raises(registry.RegistryError):
        production.load("dixon-coles-0123456789abcdef")
