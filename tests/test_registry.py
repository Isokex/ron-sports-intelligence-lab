"""Artifact registry tests.

Each test names the failure it prevents. The registry is governance code: a
record that validates is later treated as evidence, so every "should fail"
case here is a way a research model could otherwise drift toward production.
"""
import hashlib
import json
import os

import pytest

from rsil import registry


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def base_record(**overrides) -> dict:
    record = {
        "artifact_id": "dixon-coles-0123456789abcdef",
        "artifact_schema": registry.ARTIFACT_SCHEMA_VERSION,
        "model_family": "dixon-coles",
        "dataset": {
            "manifest_hash": sha("corpus-v1"),
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
            "config_sha256": sha("config"),
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


def test_valid_record_passes():
    assert registry.validate(base_record(), verify_files=False)["research_only"] is True


def test_record_without_artifact_id_fails():
    record = base_record()
    del record["artifact_id"]
    with pytest.raises(registry.RegistryError) as exc:
        registry.validate(record, verify_files=False)
    assert exc.value.code == "missing:artifact_id"


@pytest.mark.parametrize("field", ["dataset", "provenance", "training", "evaluation",
                                   "metrics", "code_commit", "created_at", "files"])
def test_missing_required_block_fails(field):
    record = base_record()
    del record[field]
    with pytest.raises(registry.RegistryError) as exc:
        registry.validate(record, verify_files=False)
    assert exc.value.code == f"missing:{field}"


def test_missing_dataset_hash_fails():
    record = base_record()
    del record["dataset"]["manifest_hash"]
    with pytest.raises(registry.RegistryError) as exc:
        registry.validate(record, verify_files=False)
    assert exc.value.code == "invalid:dataset.manifest_hash"


def test_missing_licence_reference_fails():
    record = base_record()
    del record["provenance"]["sources"][0]["licence_reference"]
    del record["provenance"]["sources"][0]["licence"]
    with pytest.raises(registry.RegistryError) as exc:
        registry.validate(record, verify_files=False)
    assert exc.value.code == "missing:provenance.licence"


def test_missing_eligibility_fails():
    record = base_record()
    del record["provenance"]["eligibility"]
    with pytest.raises(registry.RegistryError) as exc:
        registry.validate(record, verify_files=False)
    assert exc.value.code == "missing:provenance.eligibility"


def test_missing_hyperparameters_fails():
    record = base_record()
    record["training"]["hyperparameters"] = {}
    with pytest.raises(registry.RegistryError) as exc:
        registry.validate(record, verify_files=False)
    assert exc.value.code == "missing:training.hyperparameters"


def test_missing_calibration_fails():
    record = base_record()
    record["metrics"]["calibration"] = []
    with pytest.raises(registry.RegistryError) as exc:
        registry.validate(record, verify_files=False)
    assert exc.value.code == "missing:metrics.calibration"


def test_random_split_is_refused():
    record = base_record()
    record["evaluation"]["random_split"] = True
    with pytest.raises(registry.RegistryError) as exc:
        registry.validate(record, verify_files=False)
    assert exc.value.code == "invalid:evaluation.random_split"


def test_unknown_field_is_refused():
    record = base_record()
    record["production_ready"] = True
    with pytest.raises(registry.RegistryError) as exc:
        registry.validate(record, verify_files=False)
    assert exc.value.code.startswith("unexpected:")


def test_research_only_false_fails():
    record = base_record()
    record["research_only"] = False
    with pytest.raises(registry.RegistryError) as exc:
        registry.validate(record, verify_files=False)
    assert exc.value.code == "research_only_required"


def test_production_approval_is_refused_not_downgraded():
    record = base_record()
    record["production_approved"] = True
    with pytest.raises(registry.RegistryError) as exc:
        registry.validate(record, verify_files=False)
    assert exc.value.code == "production_approval_not_supported"


def test_created_at_must_be_utc():
    record = base_record()
    record["created_at"] = "2026-11-25T00:00:00+01:00"
    with pytest.raises(registry.RegistryError) as exc:
        registry.validate(record, verify_files=False)
    assert exc.value.code == "invalid:created_at"


def test_code_commit_must_be_full_sha():
    record = base_record()
    record["code_commit"] = "abc1234"
    with pytest.raises(registry.RegistryError) as exc:
        registry.validate(record, verify_files=False)
    assert exc.value.code == "invalid:code_commit"


def test_checksum_mismatch_fails(tmp_path):
    record = base_record()
    target = tmp_path / "data/artifacts/dixon-coles-v1/params.json"
    target.parent.mkdir(parents=True)
    target.write_text("different bytes")
    with pytest.raises(registry.RegistryError) as exc:
        registry.validate(record, base_dir=str(tmp_path), verify_files=True)
    assert exc.value.code == "checksum_mismatch"


def test_missing_file_fails(tmp_path):
    record = base_record()
    with pytest.raises(registry.RegistryError) as exc:
        registry.validate(record, base_dir=str(tmp_path), verify_files=True)
    assert exc.value.code == "file_missing"


def test_checksum_match_passes(tmp_path):
    record = base_record()
    target = tmp_path / "data/artifacts/dixon-coles-v1/params.json"
    target.parent.mkdir(parents=True)
    target.write_text("weights")
    record["files"][0]["sha256"] = hashlib.sha256(b"weights").hexdigest()
    assert registry.validate(record, base_dir=str(tmp_path))["files"]


@pytest.mark.parametrize("path", [
    "src/rsil/model.pkl",
    "tests/fixtures/weights.npz",
    "artifacts/research/x/weights.pkl",
    "../outside.json",
    "/abs/weights.pkl",
])
def test_committing_weights_is_refused(path):
    record = base_record()
    record["files"] = [{"path": path, "sha256": sha("x")}]
    with pytest.raises(registry.RegistryError) as exc:
        registry.validate(record, verify_files=False)
    assert exc.value.code in ("tracked_path_refused", "invalid:files.path")


def test_artifact_id_is_deterministic_and_dataset_sensitive():
    first = registry.artifact_id("dixon-coles", sha("a"), sha("b"))
    again = registry.artifact_id("dixon-coles", sha("a"), sha("b"))
    other = registry.artifact_id("dixon-coles", sha("c"), sha("b"))
    assert first == again and first != other and first.startswith("dixon-coles-")


def test_build_record_sets_research_flags():
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
                 "calibration": [{"bin": 0.5, "observed": 0.5}]},
        created_at="2026-11-25T00:00:00Z",
        files=[],
    )
    assert record["research_only"] is True
    assert record["production_approved"] is False
    assert record["artifact_id"].startswith("elo-")


def test_write_record_writes_only_metadata(tmp_path):
    record = base_record()
    path = registry.write_record(record, root=str(tmp_path / "artifacts/research"),
                                verify_files=False)
    assert os.path.basename(path) == "metadata.json"
    assert json.load(open(path))["artifact_id"] == record["artifact_id"]
    registry.assert_metadata_only(str(tmp_path / "artifacts/research"))


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


def test_production_registry_refuses_everything():
    production = registry.ProductionArtifactRegistry()
    with pytest.raises(registry.RegistryError) as exc:
        production.register(base_record())
    assert exc.value.code == "production_registry_not_available"
    with pytest.raises(registry.RegistryError):
        production.load("dixon-coles-0123456789abcdef")
