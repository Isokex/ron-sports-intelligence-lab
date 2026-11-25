"""Temporal model, deterministic identity, strict types and licensing provenance."""
import json
import os

import pytest

from rsil import corpus, manifest as manifest_mod
from rsil.providers import CsvMappedProvider, SourceMeta, Verification
from rsil.quality import validate, validate_observations
from rsil.schema import record_from_mapping
from rsil import temporal

KICKOFF = "2024-02-03T15:00:00+00:00"
BEFORE = "2024-02-03T14:00:00+00:00"
AFTER = "2024-02-03T17:00:00+00:00"
LATER = "2024-02-05T09:00:00+00:00"


def raw(**over):
    row = {"competition_id": "c1", "competition_name": "League",
           "season": "2024", "match_id": "m1", "kickoff_utc": KICKOFF,
           "status": "FT", "home_team_name": "Alpha", "away_team_name": "Beta",
           "home_goals": 2, "away_goals": 1, "available_at": AFTER,
           "source_name": "unit"}
    row.update(over)
    return row


def record(**over):
    rec, reason = record_from_mapping(raw(**over), "unit", AFTER)
    assert rec is not None, reason
    return rec.row()


class Stub:
    """Minimal adapter: fixed records, fixed completeness, fixed permissions."""

    def __init__(self, records, observations=(), complete=True,
                 permitted=None, verification=None):
        self.records = list(records)
        self.observations = list(observations)
        self.complete = complete
        self.meta = SourceMeta(
            name="stub", licence="CC0-1.0", licence_url="", attribution="",
            source_url="", retrieved_at="2024-02-06T00:00:00+00:00",
            permitted=permitted or {"research": True},
            verification=verification or Verification())
        self.is_synthetic = True

    def fetch(self):
        from rsil.providers import ProviderResult
        return ProviderResult(records=self.records, complete=self.complete,
                              meta=self.meta, observations=self.observations)


# ── temporal model ──────────────────────────────────────────────────

def test_pre_kickoff_odds_and_lineups_are_valid_observations():
    obs = [
        {"match_key": "c1|2024|m1", "kind": "pre_match_odds",
         "available_at": BEFORE, "payload": {"home": 2.1}},
        {"match_key": "c1|2024|m1", "kind": "pre_match_lineup",
         "available_at": "2024-02-03T14:30:00+00:00", "payload": {"xi": 11}},
    ]
    report = validate_observations(obs)
    assert report["counts"]["accepted"] == 2
    assert [o.kind for o in report["accepted"]] == ["pre_match_odds",
                                                    "pre_match_lineup"]


def test_match_outcome_timestamp_before_kickoff_is_a_warning_not_a_rejection():
    report = validate([raw(available_at=BEFORE)])
    assert report.counts()["accepted"] == 1
    assert report.counts()["errors"] == 0
    assert any(f.code == "result_available_before_kickoff"
               and f.severity == "WARNING" for f in report.findings)


def test_post_match_result_is_invisible_at_kickoff_and_visible_after():
    row = record()
    view = temporal.temporal_view([row], [], KICKOFF)
    assert view["results"] == [] and view["excluded"]["results"] == 1
    view_later = temporal.temporal_view([row], [], AFTER)
    assert len(view_later["results"]) == 1


def test_late_correction_is_visible_only_after_it_arrives():
    correction = {"match_key": "c1|2024|m1", "kind": "correction",
                  "available_at": LATER, "payload": {"away_goals": 2}}
    early = temporal.temporal_view([record()], [correction], AFTER)
    late = temporal.temporal_view([record()], [correction], LATER)
    assert early["observations"] == []
    assert len(late["observations"]) == 1


def test_future_dated_observation_is_excluded_and_counted():
    future = {"match_key": "c1|2024|m1", "kind": "post_match_stats",
              "available_at": "2030-01-01T00:00:00+00:00", "payload": {"xg": 1.2}}
    view = temporal.temporal_view([record()], [future], AFTER)
    assert view["observations"] == []
    assert view["excluded"]["observations"] == 1


def test_results_cannot_leak_into_pre_match_features():
    target = record()
    played = record(match_id="m0", kickoff_utc="2024-01-27T15:00:00+00:00",
                    available_at="2024-01-27T17:00:00+00:00")
    not_yet = record(match_id="m2", kickoff_utc="2024-02-03T14:00:00+00:00",
                     available_at=AFTER)
    inputs = temporal.feature_inputs(target, [played, not_yet], [], KICKOFF)
    assert [m["match_id"] for m in inputs["history"]] == ["m0"]
    assert inputs["label_visible"] is False
    assert inputs["excluded"]["history"] == 1


def test_assert_no_leakage_rejects_future_records():
    with pytest.raises(temporal.TemporalError):
        temporal.assert_no_leakage([record()], KICKOFF)
    temporal.assert_no_leakage([record()], AFTER)


def test_naive_and_invalid_timestamps_are_rejected():
    assert record_from_mapping(raw(kickoff_utc="2024-02-03T15:00:00"),
                               "unit", AFTER)[1] == "naive_timestamp:kickoff_utc"
    assert record_from_mapping(raw(kickoff_utc="not-a-time"),
                               "unit", AFTER)[1] == "invalid_timestamp:kickoff_utc"


def test_unknown_observation_kind_is_rejected():
    report = validate_observations([{"match_key": "c1|2024|m1",
                                     "kind": "team_bus_arrival",
                                     "available_at": BEFORE}])
    assert report["counts"]["rejected"] == 1
    assert "unknown_kind:team_bus_arrival" in report["reasons"]


# ── strict types ────────────────────────────────────────────────────

@pytest.mark.parametrize("field,value,code", [
    ("home_goals", "2.5", "not_an_integer:home_goals"),
    ("shots_home", "many", "not_an_integer:shots_home"),
    ("xg_home", "NaN", "not_a_number:xg_home"),
    ("odds_home", "2.0.1", "not_a_number:odds_home"),
])
def test_lossy_or_malformed_numbers_are_rejected_with_reasons(field, value, code):
    assert record_from_mapping(raw(**{field: value}), "unit", AFTER)[1] == code


def test_decimal_integer_is_never_truncated():
    assert record_from_mapping(raw(home_goals="2.0"), "unit", AFTER)[0].home_goals == 2
    assert record_from_mapping(raw(home_goals=2.7), "unit", AFTER)[1] == \
        "not_an_integer:home_goals"


def test_timestamps_are_normalised_to_utc():
    rec = record_from_mapping(raw(kickoff_utc="2024-02-03T16:00:00+01:00"),
                              "unit", AFTER)[0]
    assert rec.kickoff_utc == "2024-02-03T15:00:00+00:00"


# ── deterministic identity ──────────────────────────────────────────

def test_same_match_id_in_two_competitions_stays_distinct():
    report = validate([raw(), raw(competition_id="c2", competition_name="Cup")])
    assert report.counts()["accepted"] == 2
    keys = [rec.match_key for rec in report.accepted]
    assert keys == ["c1|2024|m1", "c2|2024|m1"]
    assert len(set(keys)) == 2


def test_identical_records_across_sources_are_duplicates_not_conflicts():
    report = validate([raw(), raw(source_name="other")])
    assert report.counts()["duplicates"] == 1
    assert report.counts()["conflicts"] == 0


def test_hash_is_order_independent_and_version_sensitive():
    rows = [record(), record(match_id="m0")]
    assert manifest_mod.content_hash(rows) == \
        manifest_mod.content_hash(list(reversed(rows)))
    assert manifest_mod.content_hash(rows, "rsil-match-v1") != \
        manifest_mod.content_hash(rows, "rsil-match-v2")


# ── licensing provenance and completeness ───────────────────────────

def test_csv_spec_cannot_grant_itself_production_permission(tmp_path):
    csv_path = tmp_path / "d.csv"
    csv_path.write_text("k,h,a,hg,ag,st\n2024-02-03T15:00:00+00:00,X,Y,1,0,FT\n")
    spec = {"meta": {"name": "claims-everything", "licence": "proprietary",
                     "permitted": {"research": True,
                                   "production_training": True,
                                   "redistribution": True},
                     "verification": {"status": "APPROVED", "by": "spec",
                                      "at": "2024-01-01", "scope": "all"},
                     "retrievedAt": AFTER},
            "constants": {"season": "2024", "competition_id": "c1",
                          "match_id": "m1", "available_at": AFTER},
            "columns": {"kickoff_utc": "k", "home_team_name": "h",
                        "away_team_name": "a", "home_goals": "hg",
                        "away_goals": "ag", "status": "st"}}
    spec_path = tmp_path / "s.json"
    spec_path.write_text(json.dumps(spec))
    built = corpus.build(CsvMappedProvider(str(csv_path), str(spec_path)),
                         str(tmp_path / "out"))
    assert built["source"]["permissions"]["declared"]["production_training"] is True
    assert built["source"]["permissions"]["verified"]["status"] == "UNVERIFIED"
    assert built["productionEligible"] is False
    assert built["productionEligibilityReason"] == "permissions_unverified"


def test_verified_permission_is_required_for_production_eligibility(tmp_path):
    approved = Verification(status="APPROVED", by="ceo", at="2024-02-06",
                            scope="production_training", evidence_url="mail://1")
    built = corpus.build(Stub([raw()], permitted={"research": True,
                                                  "production_training": True},
                              verification=approved), str(tmp_path / "ok"))
    assert built["productionEligible"] is True


def test_incomplete_scan_is_partial_and_never_production_eligible(tmp_path):
    built = corpus.build(Stub([raw()], complete=False), str(tmp_path / "p"))
    assert built["completeness"] == "PARTIAL"
    assert built["productionEligible"] is False
    assert built["productionEligibilityReason"] == "scan_incomplete"
    assert built["counts"]["accepted"] == 1


def test_failed_ingestion_writes_no_manifest(tmp_path):
    class Boom(Stub):
        def fetch(self):
            raise RuntimeError("source interrupted")
    out = tmp_path / "boom"
    with pytest.raises(RuntimeError):
        corpus.build(Boom([]), str(out))
    assert not os.path.exists(out / "manifest.json")


def test_observations_are_written_as_their_own_partition(tmp_path):
    obs = [{"match_key": "c1|2024|m1", "kind": "pre_match_odds",
            "available_at": BEFORE, "payload": {"home": 2.1}}]
    built = corpus.build(Stub([raw()], observations=obs), str(tmp_path / "o"))
    assert built["observationCounts"]["accepted"] == 1
    assert built["observationPartition"]["rows"] == 1
    assert os.path.exists(os.path.join(str(tmp_path / "o"),
                                       built["observationPartition"]["path"]))


def test_rerun_is_byte_identical_including_versions(tmp_path):
    a = corpus.build(Stub([raw()]), str(tmp_path / "a"))
    b = corpus.build(Stub([raw()]), str(tmp_path / "b"))
    assert a["contentHash"] == b["contentHash"]
    assert a["partitions"][0]["sha256"] == b["partitions"][0]["sha256"]
    assert a["schemaVersion"] == b["schemaVersion"] == "rsil-match-v2"
    assert a["transformVersion"] == b["transformVersion"]


# --- target prediction timestamp enforcement (pre-match invariant) ---

def test_features_at_kickoff_are_permitted():
    out = temporal.prematch_feature_inputs(record(), [], [], KICKOFF)
    assert out["asOf"] == KICKOFF
    assert out["label_visible"] is False


def test_features_before_kickoff_are_permitted():
    out = temporal.prematch_feature_inputs(record(), [], [], BEFORE)
    assert out["asOf"] == BEFORE
    assert out["label_visible"] is False


def test_features_after_kickoff_are_rejected():
    with pytest.raises(temporal.TemporalError) as err:
        temporal.prematch_feature_inputs(record(), [], [], AFTER)
    assert str(err.value) == "prediction_after_kickoff"


def test_post_match_results_remain_available_as_labels():
    doc = record()
    assert temporal.training_labels([doc], KICKOFF) == []
    labels = temporal.training_labels([doc], AFTER)
    assert len(labels) == 1
    example = temporal.training_example(doc, [], [], BEFORE,
                                        label_as_of=AFTER)
    assert example["label_visible"] is True


def test_post_match_observations_cannot_enter_prematch_features():
    doc = record()
    obs = [{"match_key": doc["match_key"], "kind": "result",
            "available_at": AFTER, "payload": {}, "source_name": "s",
            "source_record_id": "r1"}]
    out = temporal.prematch_feature_inputs(doc, [], obs, KICKOFF)
    assert out["observations"] == []
    assert out["excluded"]["post_match_observations"] == 1


def test_dataset_builder_shares_the_same_invariant():
    with pytest.raises(temporal.TemporalError):
        temporal.training_example(record(), [], [], AFTER)
    assert temporal.feature_inputs is temporal.prematch_feature_inputs
