"""Provider-neutral corpus: schema, validation, dedupe, partitions, manifests."""
import json
import os

import pytest

from rsil import cli, corpus
from rsil.providers import (CsvMappedProvider, ProviderError, SourceMeta,
                            SyntheticProvider, ensure_research_allowed)
from rsil.quality import validate
from rsil.schema import record_from_mapping

KICKOFF = "2023-08-12T15:00:00+00:00"
AFTER = "2023-08-12T17:05:00+00:00"


def row(**over):
    base = {
        "competition_id": "c1", "competition_name": "League One",
        "season": "2023", "match_id": "m1", "kickoff_utc": KICKOFF,
        "status": "FT", "home_team_id": "t1", "home_team_name": "Alpha",
        "away_team_id": "t2", "away_team_name": "Beta",
        "home_goals": 2, "away_goals": 1, "ht_home_goals": 1, "ht_away_goals": 0,
        "shots_home": 12, "shots_away": 9, "shots_on_target_home": 5,
        "shots_on_target_away": 3, "xg_home": 1.8, "xg_away": 1.1,
        "odds_home": 1.9, "odds_draw": 3.4, "odds_away": 4.2,
        "odds_captured_at": "2023-08-12T14:00:00+00:00",
        "available_at": AFTER, "source_name": "unit", "source_record_id": "r1",
        "source_url": "", "ingested_at": AFTER, "is_synthetic": True,
    }
    base.update(over)
    return base


def _meta(**over):
    permitted = {"research": True, "production_training": False,
                 "redistribution": False}
    permitted.update(over.pop("permitted", {}))
    return SourceMeta(name=over.get("name", "unit"), licence="CC0-1.0",
                      licence_url="", attribution="", source_url="",
                      retrieved_at=AFTER, permitted=permitted)


def test_schema_rejects_missing_required_and_keeps_good_rows():
    rec, reason = record_from_mapping({"match_id": "m1"}, "unit", AFTER)
    assert rec is None and reason.startswith("missing:")
    good, reason = record_from_mapping(row(), "unit", AFTER)
    assert reason is None and good.match_id == "m1" and good.is_synthetic


def test_malformed_row_is_rejected_with_a_reason():
    report = validate(["not-a-mapping"], source_name="unit", ingested_at=AFTER)
    assert report.counts()["accepted"] == 0
    assert report.reasons() == {"not_a_mapping": 1}


@pytest.mark.parametrize("override,code", [
    ({"kickoff_utc": "not-a-date"}, "invalid_kickoff"),
    ({"available_at": "2023-08-12T14:00:00+00:00"}, "available_before_kickoff"),
    ({"away_team_name": "Alpha"}, "self_match"),
    ({"home_goals": -1}, "impossible_score"),
    ({"home_goals": 99}, "impossible_score"),
    ({"status": "NS"}, "score_on_unfinished_match"),
    ({"odds_home": 0.9}, "invalid_odds"),
    ({"xg_home": -0.2}, "invalid_xg"),
])
def test_invalid_records_are_rejected_with_specific_codes(override, code):
    report = validate([row(**override)], source_name="unit", ingested_at=AFTER)
    assert report.counts()["accepted"] == 0
    assert report.reasons() == {code: 1}


def test_duplicate_identical_rows_are_counted_not_stored_twice():
    report = validate([row(), row()], source_name="unit", ingested_at=AFTER)
    assert report.counts()["accepted"] == 1 and report.counts()["duplicates"] == 1


def test_conflicting_result_keeps_first_and_records_the_conflict():
    report = validate([row(), row(home_goals=0, away_goals=3)],
                      source_name="unit", ingested_at=AFTER)
    assert report.counts()["accepted"] == 1
    assert report.conflicts[0]["match_id"] == "m1"
    assert report.accepted[0].home_goals == 2


def test_build_writes_partitions_and_a_hashed_manifest(tmp_path):
    manifest = corpus.build(SyntheticProvider(competitions=2, seasons=2),
                            str(tmp_path), created_at=AFTER)
    assert manifest["completeness"] == "COMPLETE"
    assert manifest["counts"]["accepted"] == 120
    assert len(manifest["partitions"]) == 4
    for part in manifest["partitions"]:
        assert os.path.exists(tmp_path / part["path"])
        assert part["sha256"] and part["rows"] > 0
    assert (tmp_path / "manifest.json").exists()


def test_manifest_records_source_licence_and_permitted_use(tmp_path):
    manifest = corpus.build(SyntheticProvider(), str(tmp_path), created_at=AFTER)
    source = manifest["source"]
    assert source["licence"] == "CC0-1.0"
    assert set(source["permitted"]) == {"research", "production_training",
                                        "redistribution"}
    assert manifest["suitableForProductionTraining"] is False
    assert manifest["schemaVersion"].startswith("rsil-match")


def test_rerunning_unchanged_source_produces_identical_output(tmp_path):
    first = corpus.build(SyntheticProvider(), str(tmp_path / "a"), created_at=AFTER)
    second = corpus.build(SyntheticProvider(), str(tmp_path / "b"), created_at=AFTER)
    assert first["contentHash"] == second["contentHash"]
    assert first["partitions"] == second["partitions"]
    for part in first["partitions"]:
        a = (tmp_path / "a" / part["path"]).read_bytes()
        b = (tmp_path / "b" / part["path"]).read_bytes()
        assert a == b, "parquet output must be byte-identical"


def test_changed_source_data_changes_the_content_hash(tmp_path):
    base = corpus.build(SyntheticProvider(seasons=1), str(tmp_path / "a"),
                        created_at=AFTER)
    more = corpus.build(SyntheticProvider(seasons=2), str(tmp_path / "b"),
                        created_at=AFTER)
    assert base["contentHash"] != more["contentHash"]


def test_partial_fetch_is_marked_partial(tmp_path):
    manifest = corpus.build(SyntheticProvider(complete=False),
                            str(tmp_path), created_at=AFTER)
    assert manifest["completeness"] == "PARTIAL"
    assert manifest["notes"] == ["simulated partial fetch"]
    assert cli.main(["ingest", "--provider", "synthetic", "--partial",
                     "--out", str(tmp_path / "cli")]) == 3


def test_provider_without_research_permission_is_refused(tmp_path):
    meta = _meta(permitted={"research": False})
    with pytest.raises(ProviderError):
        ensure_research_allowed(meta)
    provider = SyntheticProvider()
    provider.meta = meta
    with pytest.raises(ProviderError):
        corpus.build(provider, str(tmp_path), created_at=AFTER)


def test_csv_provider_maps_columns_and_reports_rejections(tmp_path):
    csv_path = tmp_path / "demo.csv"
    csv_path.write_text(
        "date,home,away,hg,ag,comp,status\n"
        "2023-08-12T15:00:00+00:00,Alpha,Beta,2,1,c1,FT\n"
        "2023-08-13T15:00:00+00:00,Gamma,Delta,1,1,c1,FT\n"
        ",Broken,Row,0,0,c1,FT\n")
    spec = {
        "meta": {"name": "demo", "licence": "CC0-1.0", "licenceUrl": "",
                 "attribution": "generated demo", "sourceUrl": "",
                 "retrievedAt": AFTER, "synthetic": True,
                 "permitted": {"research": True}},
        "constants": {"season": "2023"},
        "columns": {"kickoff_utc": "date", "home_team_name": "home",
                    "away_team_name": "away", "home_goals": "hg",
                    "away_goals": "ag", "competition_id": "comp",
                    "match_id": "date", "available_at": "date",
                    "status": "status"},
    }
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec))
    provider = CsvMappedProvider(str(csv_path), str(spec_path))
    manifest = corpus.build(provider, str(tmp_path / "out"), created_at=AFTER)
    assert manifest["source"]["name"] == "demo"
    assert manifest["counts"]["accepted"] == 2
    assert manifest["counts"]["rejected"] == 1
    assert manifest["rejectionReasons"]
