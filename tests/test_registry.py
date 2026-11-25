"""Artifact registry tests.

Each test names the failure it prevents. The registry is governance code: a
record that validates is later treated as evidence, so every "should fail" case
here is a way a research model could otherwise drift toward production, or a way
a record could misdescribe what it was trained on.
"""
import hashlib
import json
import os
import threading

import pytest

from rsil import registry


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


DATASET_HASH = sha("corpus-v1")
CONFIG_HASH = sha("config")


def base_record(**overrides) -> dict:
    """A valid metadata-only record. File references are added per test."""
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
            "calibration": [{"bin": 0.1, "predicted": 0.1, "observed": 0.12, "n": 380}],
        },
        "created_at": "2026-11-25T00:00:00Z",
        "files": [],
        "research_only": True,
        "production_approved": False,
    }
    record.update(overrides)
    return record


def check(record, **kwargs):
    return registry.validate(record, **kwargs)


def error_code(record, **kwargs) -> str:
    with pytest.raises(registry.RegistryError) as exc:
        check(record, **kwargs)
    return exc.value.code


def with_file(path: str, content: str = "weights", **overrides) -> dict:
    record = base_record(**overrides)
    record["files"] = [{"path": path,
                        "sha256": hashlib.sha256(content.encode()).hexdigest()}]
    return record


def write_file_under(tmp_path, relative: str, content: str = "weights"):
    target = tmp_path / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return target


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
# production eligibility is a Boolean false or nothing
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
# 1. file references are always verified, never optionally
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
    assert error_code(with_file(path)) == code


def test_duplicate_file_entries_are_refused():
    record = with_file("data/artifacts/x/params.json")
    record["files"] = [record["files"][0], dict(record["files"][0])]
    assert error_code(record) == "invalid:files"


def test_symlink_escape_from_data_is_refused(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "weights.json").write_text("weights")
    data = tmp_path / "data"
    data.mkdir()
    os.symlink(outside / "weights.json", data / "link.json")
    with pytest.raises(registry.RegistryError) as exc:
        registry.validate(with_file("data/link.json"), base_dir=str(tmp_path))
    assert exc.value.code == "symlink_escape"


def test_symlink_into_tracked_content_is_refused(tmp_path):
    tracked = tmp_path / "src"
    tracked.mkdir()
    (tracked / "model.py").write_text("weights")
    data = tmp_path / "data"
    data.mkdir()
    os.symlink(tracked / "model.py", data / "link.json")
    with pytest.raises(registry.RegistryError) as exc:
        registry.validate(with_file("data/link.json"), base_dir=str(tmp_path))
    assert exc.value.code in ("symlink_escape", "tracked_path_refused")


def test_file_references_without_base_dir_fail():
    assert error_code(with_file("data/artifacts/x/params.json")) == "base_dir_required"


def test_no_files_needs_no_base_dir():
    assert registry.validate(base_record())["files"] == []


def test_registration_with_file_references_requires_base_dir(tmp_path):
    root = str(tmp_path / "artifacts/research")
    with pytest.raises(registry.RegistryError) as exc:
        registry.write_record(with_file("data/artifacts/x/params.json"), root=root)
    assert exc.value.code == "base_dir_required"
    assert not os.path.exists(os.path.join(root, base_record()["artifact_id"],
                                           "metadata.json"))


def test_registration_verifies_files(tmp_path):
    root = str(tmp_path / "artifacts/research")
    record = with_file("data/artifacts/x/params.json", content="weights")
    write_file_under(tmp_path, "data/artifacts/x/params.json", "weights")
    path = registry.write_record(record, root=root, base_dir=str(tmp_path))
    assert os.path.basename(path) == "metadata.json"


def test_registration_refuses_wrong_checksum(tmp_path):
    root = str(tmp_path / "artifacts/research")
    record = with_file("data/artifacts/x/params.json", content="weights")
    write_file_under(tmp_path, "data/artifacts/x/params.json", "different")
    with pytest.raises(registry.RegistryError) as exc:
        registry.write_record(record, root=root, base_dir=str(tmp_path))
    assert exc.value.code == "checksum_mismatch"


def test_registration_refuses_missing_file(tmp_path):
    root = str(tmp_path / "artifacts/research")
    record = with_file("data/artifacts/x/params.json")
    (tmp_path / "data").mkdir()
    with pytest.raises(registry.RegistryError) as exc:
        registry.write_record(record, root=root, base_dir=str(tmp_path))
    assert exc.value.code == "file_missing"


def test_checksum_match_passes(tmp_path):
    write_file_under(tmp_path, "data/artifacts/x/params.json", "weights")
    record = with_file("data/artifacts/x/params.json", content="weights")
    assert registry.validate(record, base_dir=str(tmp_path))["files"]


# --------------------------------------------------------------------------- #
# 2. nested values are walked recursively
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nested_hyperparameter_must_be_finite(value):
    record = base_record()
    record["training"]["hyperparameters"]["nested"] = {"xi": [value]}
    assert error_code(record) == "non_finite_value"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nested_note_must_be_finite(value):
    record = base_record()
    record["provenance"]["notes"] = {"review": [{"value": value}]}
    assert error_code(record) == "non_finite_value"


@pytest.mark.parametrize("field", ["log_loss", "brier", "ece"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_metric_is_refused(field, value):
    record = base_record()
    record["metrics"][field] = value
    assert error_code(record) == "non_finite_value"


def test_build_record_rejects_nested_non_finite():
    provenance = base_record()["provenance"]
    provenance["notes"] = {"clean": float("inf")}
    with pytest.raises(registry.RegistryError) as exc:
        registry.build_record(
            model_family="elo",
            dataset={"manifest_hash": sha("corpus"), "corpus_version": "v1"},
            provenance=provenance,
            schema_version="rsil-match-v2",
            feature_version="features-v1",
            training={"config_sha256": sha("cfg"), "hyperparameters": {"K": 20}},
            code_commit="b" * 40,
            evaluation={"protocol": "walk_forward",
                        "splits": [{"test_season": "2022-23",
                                    "train_seasons": ["2021-22"]}]},
            metrics={"log_loss": 1.0, "brier": 0.6, "ece": 0.05, "n": 10,
                     "calibration": [{"bin": 0.5, "observed": 0.5, "n": 10}]},
            created_at="2026-11-25T00:00:00Z",
            files=[],
        )
    assert exc.value.code == "non_finite_value"


def test_write_record_rejects_nested_non_finite(tmp_path):
    record = base_record()
    record["training"]["hyperparameters"]["scale"] = float("nan")
    with pytest.raises(registry.RegistryError) as exc:
        registry.write_record(record, root=str(tmp_path / "reg"))
    assert exc.value.code == "non_finite_value"


def test_unsupported_json_type_is_refused():
    record = base_record()
    record["provenance"]["notes"] = {"blob": b"bytes"}
    assert error_code(record) == "unsupported_json_value"


def test_load_record_rejects_non_finite_json(tmp_path):
    path = tmp_path / "metadata.json"
    path.write_text('{"log_loss": NaN}')
    with pytest.raises(registry.RegistryError) as exc:
        registry.load_record(str(path))
    assert exc.value.code == "invalid:json"


def test_serialization_failure_is_a_registry_error(tmp_path):
    record = base_record()
    record["provenance"]["notes"] = {"blob": b"bytes"}
    with pytest.raises(registry.RegistryError) as exc:
        registry.write_record(record, root=str(tmp_path / "reg"))
    assert exc.value.code in ("unsupported_json_value", "serialization_failed")


# --------------------------------------------------------------------------- #
# 3. calibration counts reconcile with the sample size
# --------------------------------------------------------------------------- #

def test_calibration_totals_matching_n_pass():
    record = base_record()
    record["metrics"]["n"] = 100
    record["metrics"]["calibration"] = [
        {"bin": 0.1, "observed": 0.1, "n": 60},
        {"bin": 0.6, "observed": 0.55, "n": 40},
    ]
    assert check(record)["metrics"]["n"] == 100


def test_calibration_undercounting_fails():
    record = base_record()
    record["metrics"]["n"] = 100
    record["metrics"]["calibration"] = [
        {"bin": 0.1, "observed": 0.1, "n": 60},
        {"bin": 0.6, "observed": 0.55, "n": 30},
    ]
    assert error_code(record) == "calibration_total_mismatch"


def test_calibration_overcounting_fails():
    record = base_record()
    record["metrics"]["n"] = 100
    record["metrics"]["calibration"] = [
        {"bin": 0.1, "observed": 0.1, "n": 60},
        {"bin": 0.6, "observed": 0.55, "n": 50},
    ]
    assert error_code(record) == "calibration_total_mismatch"


@pytest.mark.parametrize("key,value,code", [
    ("bin", 1.4, "invalid:metrics.calibration.bin"),
    ("bin", -0.1, "invalid:metrics.calibration.bin"),
    ("observed", 2.0, "invalid:metrics.calibration.observed"),
    ("observed", float("nan"), "non_finite_value"),
    ("predicted", 1.2, "invalid:metrics.calibration.predicted"),
    ("n", 0, "invalid:metrics.calibration.n"),
    ("n", "380", "invalid:metrics.calibration.n"),
])
def test_invalid_calibration_bucket_is_refused(key, value, code):
    record = base_record()
    record["metrics"]["calibration"] = [{"bin": 0.1, "observed": 0.12, "n": 380,
                                         key: value}]
    assert error_code(record) == code


def test_calibration_bucket_unknown_key_is_refused():
    record = base_record()
    record["metrics"]["calibration"] = [{"bin": 0.1, "observed": 0.1, "n": 380,
                                         "confidence": 0.9}]
    assert error_code(record).startswith("unexpected:metrics.calibration")


def test_missing_calibration_fails():
    record = base_record()
    record["metrics"]["calibration"] = []
    assert error_code(record) == "missing:metrics.calibration"


def test_sample_size_must_be_positive_integer():
    record = base_record()
    record["metrics"]["n"] = 0
    assert error_code(record) == "invalid:metrics.n"


def test_negative_log_loss_is_refused():
    record = base_record()
    record["metrics"]["log_loss"] = -0.1
    assert error_code(record) == "invalid:metrics.log_loss"


def test_ece_above_one_is_refused():
    record = base_record()
    record["metrics"]["ece"] = 1.5
    assert error_code(record) == "invalid:metrics.ece"


# --------------------------------------------------------------------------- #
# 4. atomic, immutable registration
# --------------------------------------------------------------------------- #

def test_identical_write_is_idempotent(tmp_path):
    root = str(tmp_path / "artifacts/research")
    record = base_record()
    first = registry.write_record(record, root=root)
    second = registry.write_record(record, root=root)
    assert first == second
    assert json.load(open(first))["artifact_id"] == record["artifact_id"]


def test_overwrite_with_different_metadata_is_refused(tmp_path):
    root = str(tmp_path / "artifacts/research")
    registry.write_record(base_record(), root=root)
    changed = json.loads(json.dumps(base_record()))
    changed["metrics"]["log_loss"] = 0.5
    with pytest.raises(registry.RegistryError) as exc:
        registry.write_record(changed, root=root)
    assert exc.value.code == "artifact_immutable"
    assert json.load(open(os.path.join(root, base_record()["artifact_id"],
                                       "metadata.json")))["metrics"]["log_loss"] == 0.98


def test_concurrent_writers_cannot_both_win(tmp_path):
    root = str(tmp_path / "artifacts/research")
    barrier = threading.Barrier(2)
    outcomes = {}

    def attempt(name: str, log_loss: float):
        record = json.loads(json.dumps(base_record()))
        record["metrics"]["log_loss"] = log_loss
        barrier.wait()
        try:
            registry.write_record(record, root=root)
            outcomes[name] = "ok"
        except registry.RegistryError as exc:
            outcomes[name] = exc.code

    threads = [threading.Thread(target=attempt, args=("first", 0.5)),
               threading.Thread(target=attempt, args=("second", 0.9))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(outcomes.values()) == ["artifact_immutable", "ok"]
    stored = json.load(open(os.path.join(root, base_record()["artifact_id"],
                                         "metadata.json")))
    assert stored["metrics"]["log_loss"] in (0.5, 0.9)
    registry.assert_metadata_only(root)


def test_write_leaves_only_metadata(tmp_path):
    root = str(tmp_path / "artifacts/research")
    path = registry.write_record(base_record(), root=root)
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
# identity, chronology, nested shapes
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


def test_valid_chronological_split_passes():
    record = base_record()
    record["evaluation"]["splits"] = [
        {"test_season": "2021-22", "train_seasons": ["2019-20", "2020-21"]},
        {"test_season": "2022-23", "train_seasons": ["2019-20", "2020-21", "2021-22"]},
    ]
    assert check(record)["evaluation"]["splits"]


@pytest.mark.parametrize("train_seasons", [
    ["2022-23"],
    ["2021-22"],
    ["2021-22", "2022-23"],
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
