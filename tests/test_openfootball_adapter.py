"""OpenFootball adapter, identity resolution and corpus build tests.

Payloads are built in temporary directories rather than committed as fixtures:
the real source stays outside tracked content, and each test states exactly the
shape it is exercising.
"""
import hashlib
import importlib.util
import json
import os

import pytest

from rsil import corpus, identity, temporal
from rsil.providers.base import ProviderError
from rsil.providers.openfootball import (OpenFootballAdapter, ScoreFormatError,
                                        derive_availability, normalize_score)

COMMIT = "e6744429ee395bc86f247348c6184bb08d4eb361"
ALIASES = {
    "version": "team-aliases-v1",
    "teams": [
        {"team_id": "arsenal", "display_name": "Arsenal", "aliases": ["Arsenal FC"]},
        {"team_id": "chelsea", "display_name": "Chelsea", "aliases": ["Chelsea FC", "Chelsea"]},
        {"team_id": "aston-villa", "display_name": "Aston Villa",
         "aliases": ["Aston Villa", "Aston Villa FC"]},
    ],
}


def match(day="2019-08-09", home="Arsenal FC", away="Chelsea FC", score=None,
          round_="Matchday 1", time="15:00"):
    record = {"round": round_, "date": day, "team1": home, "team2": away}
    if time is not None:
        record["time"] = time
    if score is not None:
        record["score"] = score
    return record


def make_env(tmp_path, seasons: dict, *, aliases=None, tamper=None):
    """Write a pinned source tree plus config and alias map into tmp_path."""
    root = tmp_path / "data" / "openfootball" / COMMIT
    files = []
    for season, payload in seasons.items():
        target = root / season / "en.1.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(payload).encode()
        target.write_bytes(raw)
        files.append({"season": season, "path": f"{season}/en.1.json",
                      "sha256": hashlib.sha256(raw).hexdigest(),
                      "bytes": len(raw), "source_records": len(payload["matches"])})
    config = {
        "version": "openfootball-sources-v1",
        "provider": "openfootball",
        "repository": "openfootball/football.json",
        "commit": COMMIT,
        "retrieved_at": "2026-11-25T00:00:00Z",
        "licence": {"name": "CC0-1.0", "url": f"https://example.test/{COMMIT}/LICENSE.md",
                    "attribution": "OpenFootball, CC0 1.0", "checked_at": "2026-11-25"},
        "competition": {"competition_id": "eng-premier-league",
                        "name": "English Premier League"},
        "seasons": files,
    }
    if tamper:
        for item in config["seasons"]:
            if item["season"] == tamper:
                item["sha256"] = "0" * 64
    config_path = tmp_path / "openfootball-sources.json"
    config_path.write_text(json.dumps(config))
    aliases_path = tmp_path / "team-aliases-v1.json"
    aliases_path.write_text(json.dumps(aliases or ALIASES))
    return str(root), str(config_path), str(aliases_path)


def build_adapter(tmp_path, seasons, **kwargs):
    root, config_path, aliases_path = make_env(tmp_path, seasons, **kwargs)
    return OpenFootballAdapter(source_root=root, config_path=config_path,
                               aliases_path=aliases_path)


ONE_SEASON = {"2019-20": {"name": "English Premier League 2019/20",
                          "matches": [match(score={"ht": [1, 0], "ft": [2, 1]})]}}


# --------------------------------------------------------------------------- #
# score shapes
# --------------------------------------------------------------------------- #

def test_structured_score_with_halftime():
    assert normalize_score({"ht": [1, 0], "ft": [2, 1]}) == (2, 1, 1, 0)


def test_structured_score_without_halftime():
    assert normalize_score({"ft": [2, 1]}) == (2, 1, None, None)


def test_bare_array_score():
    assert normalize_score([2, 1]) == (2, 1, None, None)


@pytest.mark.parametrize("score,code", [
    ({"ht": [1, 0]}, "missing_score"),
    ({"ft": [1, 0, 2]}, "invalid_score_pair"),
    ({"ft": [1, 0], "aet": [1, 0]}, "unsupported_score_keys"),
    ([1, 0, 2], "invalid_score_pair"),
    ("2-1", "unsupported_score_type"),
    ([[1, 0], [2, 1]], "invalid_score_value"),
])
def test_unsupported_score_structures_are_rejected(score, code):
    with pytest.raises(ScoreFormatError) as exc:
        normalize_score(score)
    assert exc.value.code == code


@pytest.mark.parametrize("score,code", [
    ([-1, 0], "invalid_score_value"),
    ([31, 0], "invalid_score_value"),
    ([1.5, 0], "invalid_score_value"),
    ([True, 0], "invalid_score_value"),
])
def test_invalid_score_values_are_rejected(score, code):
    with pytest.raises(ScoreFormatError) as exc:
        normalize_score(score)
    assert exc.value.code == code


def test_mixed_score_formats_in_one_file(tmp_path):
    payload = {"matches": [
        match(day="2019-08-09", score={"ht": [1, 0], "ft": [2, 1]}),
        match(day="2019-08-10", home="Chelsea FC", away="Aston Villa",
              score={"ft": [0, 0]}, round_="Matchday 1"),
        match(day="2019-08-11", home="Aston Villa", away="Arsenal FC",
              score=[3, 2], round_="Matchday 2"),
    ]}
    adapter = build_adapter(tmp_path, {"2019-20": payload})
    result = adapter.fetch()
    assert len(result.records) == 3
    assert adapter.score_formats == {"object:ft,ht": 1, "object:ft": 1, "list:2": 1}
    goals = {(r["home_team_id"], r["home_goals"], r["ht_home_goals"]) for r in result.records}
    assert ("arsenal", 2, 1) in goals and ("aston-villa", 3, None) in goals


def test_missing_score_is_rejected_with_reason(tmp_path):
    adapter = build_adapter(tmp_path, {"2019-20": {"matches": [match()]}})
    result = adapter.fetch()
    assert result.records == []
    assert adapter.rejections[0]["reason"] == "missing_score"


# --------------------------------------------------------------------------- #
# identity
# --------------------------------------------------------------------------- #

def test_known_aliases_resolve_to_one_identity(tmp_path):
    payload = {"matches": [
        match(day="2019-08-09", home="Aston Villa", away="Chelsea FC",
              score={"ft": [1, 1]}),
        match(day="2024-08-16", home="Aston Villa FC", away="Chelsea",
              score={"ft": [2, 2]}),
    ]}
    adapter = build_adapter(tmp_path, {"2019-20": payload})
    records = adapter.fetch().records
    assert {r["home_team_id"] for r in records} == {"aston-villa"}
    assert {r["away_team_id"] for r in records} == {"chelsea"}


def test_unknown_team_is_rejected_not_guessed(tmp_path):
    adapter = build_adapter(tmp_path, {"2019-20": {
        "matches": [match(home="Arsenall FC", score={"ft": [1, 0]})]}})
    result = adapter.fetch()
    assert result.records == []
    assert adapter.rejections[0]["reason"] == "unknown_team:Arsenall FC"


def test_no_fuzzy_matching_at_runtime(tmp_path):
    # "Arsenal" is not an alias in the map, so it must not resolve to arsenal.
    adapter = build_adapter(tmp_path, {"2019-20": {
        "matches": [match(home="Arsenal", score={"ft": [1, 0]})]}})
    adapter.fetch()
    assert adapter.rejections[0]["reason"] == "unknown_team:Arsenal"


def test_identity_mapping_rejects_alias_collisions():
    with pytest.raises(identity.IdentityError) as exc:
        identity.TeamResolver({"version": "v1", "teams": [
            {"team_id": "a", "aliases": ["Same FC"]},
            {"team_id": "b", "aliases": ["Same FC"]}]})
    assert exc.value.code == "alias_collision"


def test_identity_mapping_requires_version():
    with pytest.raises(identity.IdentityError) as exc:
        identity.TeamResolver({"teams": [{"team_id": "a", "aliases": ["A"]}]})
    assert exc.value.code == "missing_version"


def test_identity_coverage_reports_unresolved():
    resolver = identity.TeamResolver(ALIASES)
    coverage = resolver.coverage(["Arsenal FC", "Unknown FC", "Arsenal FC"])
    assert coverage["recordsCoverage"] == pytest.approx(2 / 3)
    assert coverage["unresolvedNames"] == [{"name": "Unknown FC", "count": 1}]


# --------------------------------------------------------------------------- #
# provenance and temporal contract
# --------------------------------------------------------------------------- #

def test_source_provenance_is_preserved(tmp_path):
    adapter = build_adapter(tmp_path, {"2019-20": {
        "matches": [match(score={"ht": [1, 0], "ft": [2, 1]})]}})
    adapter.fetch()
    entry = adapter.provenance[0]
    assert entry["source_team_home"] == "Arsenal FC"
    assert entry["source_score_raw"] == {"ht": [1, 0], "ft": [2, 1]}
    assert entry["source_index"] == 0
    assert entry["source_sha256"] and entry["source_round"] == "Matchday 1"
    assert entry["derivation_rule"] == "openfootball-date-only-v1"


def test_date_only_availability_is_end_of_day_plus_120_minutes(tmp_path):
    adapter = build_adapter(tmp_path, {"2019-20": {
        "matches": [match(day="2019-08-09", score={"ft": [1, 0]})]}})
    record = adapter.fetch().records[0]
    assert record["available_at"] == "2019-08-10T02:00:00+00:00"
    assert record["kickoff_utc"] == "2019-08-09T00:00:00+00:00"
    _, available, uncertainty = derive_availability("2019-08-09")
    assert available == record["available_at"]
    assert uncertainty["basis"] == "date_only"


def test_advisory_source_time_never_becomes_an_instant(tmp_path):
    early = build_adapter(tmp_path / "a", {"2019-20": {
        "matches": [match(day="2019-08-09", time="12:30", score={"ft": [1, 0]})]}})
    late = build_adapter(tmp_path / "b", {"2019-20": {
        "matches": [match(day="2019-08-09", time="20:00", score={"ft": [1, 0]})]}})
    early_row = early.fetch().records[0]
    late_row = late.fetch().records[0]
    assert early_row["available_at"] == late_row["available_at"]
    assert early.provenance[0]["source_time"] == "12:30"
    assert late.provenance[0]["source_time"] == "20:00"


def test_same_day_result_is_not_visible_to_a_prematch_cutoff(tmp_path):
    payload = {"matches": [
        match(day="2019-08-09", home="Arsenal FC", away="Chelsea FC",
              score={"ft": [2, 1]}),
        match(day="2019-08-09", home="Aston Villa", away="Chelsea FC",
              score={"ft": [0, 0]}, round_="Matchday 1"),
    ]}
    adapter = build_adapter(tmp_path, {"2019-20": payload})
    records = adapter.fetch().records
    as_of = "2019-08-09T00:00:00+00:00"
    assert temporal.visible(records, as_of) == []
    assert len(temporal.visible(records, "2019-08-10T02:00:00+00:00")) == 2


def test_source_date_anomaly_before_season_opener_is_rejected(tmp_path):
    payload = {"matches": [
        match(day="2019-08-09", score={"ft": [1, 0]}),
        match(day="2019-07-01", home="Chelsea FC", away="Aston Villa",
              score={"ft": [3, 2]}, round_="Matchday 32"),
    ]}
    adapter = build_adapter(tmp_path, {"2019-20": payload})
    result = adapter.fetch()
    assert len(result.records) == 1
    assert adapter.rejections[0]["reason"] == "date_before_season_opener"
    assert adapter.date_anomalies[0]["date"] == "2019-07-01"


# --------------------------------------------------------------------------- #
# source pinning and failure handling
# --------------------------------------------------------------------------- #

def test_source_hash_mismatch_fails_the_build(tmp_path):
    adapter = build_adapter(tmp_path, ONE_SEASON, tamper="2019-20")
    with pytest.raises(ProviderError) as exc:
        adapter.fetch()
    assert str(exc.value).startswith("source_hash_mismatch")


def test_missing_source_file_fails_the_build(tmp_path):
    root, config_path, aliases_path = make_env(tmp_path, ONE_SEASON)
    os.remove(os.path.join(root, "2019-20", "en.1.json"))
    adapter = OpenFootballAdapter(source_root=root, config_path=config_path,
                                  aliases_path=aliases_path)
    with pytest.raises(ProviderError) as exc:
        adapter.fetch()
    assert str(exc.value).startswith("source_unreadable")


def test_unpinned_commit_is_refused(tmp_path):
    root, config_path, aliases_path = make_env(tmp_path, ONE_SEASON)
    config = json.load(open(config_path))
    config["commit"] = "main"
    json.dump(config, open(config_path, "w"))
    with pytest.raises(ProviderError) as exc:
        OpenFootballAdapter(source_root=root, config_path=config_path,
                            aliases_path=aliases_path)
    assert "config_unpinned" in str(exc.value)


def test_licence_and_permissions_are_declared(tmp_path):
    adapter = build_adapter(tmp_path, ONE_SEASON)
    meta = adapter.meta.as_dict()
    assert meta["licence"] == "CC0-1.0"
    assert meta["permissions"]["declared"]["research"] is True
    assert meta["permissions"]["declared"]["production_training"] is False
    assert meta["permissions"]["verified"]["status"] == "UNVERIFIED"
    assert COMMIT in meta["sourceUrl"]


# --------------------------------------------------------------------------- #
# corpus build: duplicates, conflicts, determinism, manifest
# --------------------------------------------------------------------------- #

def test_duplicate_records_are_counted_not_duplicated(tmp_path):
    payload = {"matches": [match(score={"ft": [1, 0]}),
                           match(score={"ft": [1, 0]})]}
    adapter = build_adapter(tmp_path, {"2019-20": payload})
    manifest = corpus.build(adapter, str(tmp_path / "out"), created_at="2026-11-25T00:00:00Z")
    assert manifest["counts"]["accepted"] == 1
    assert manifest["counts"]["duplicates"] == 1


def test_conflicting_results_are_recorded_first_wins(tmp_path):
    payload = {"matches": [match(score={"ft": [1, 0]}),
                           match(score={"ft": [0, 2]})]}
    adapter = build_adapter(tmp_path, {"2019-20": payload})
    manifest = corpus.build(adapter, str(tmp_path / "out"), created_at="2026-11-25T00:00:00Z")
    assert manifest["counts"]["accepted"] == 1
    assert len(manifest["conflicts"]) == 1
    assert manifest["conflicts"][0]["kept"][:2] == [1, 0]


def test_build_is_deterministic_and_reproducible(tmp_path):
    payload = {"matches": [
        match(day="2019-08-09", score={"ht": [1, 0], "ft": [2, 1]}),
        match(day="2019-08-10", home="Chelsea FC", away="Aston Villa",
              score={"ft": [0, 0]}),
    ]}
    first = build_adapter(tmp_path / "one", {"2019-20": payload})
    second = build_adapter(tmp_path / "two", {"2019-20": payload})
    manifest_a = corpus.build(first, str(tmp_path / "a"), created_at="2026-11-25T00:00:00Z")
    manifest_b = corpus.build(second, str(tmp_path / "b"), created_at="2026-11-25T00:00:00Z")
    assert manifest_a["contentHash"] == manifest_b["contentHash"]
    assert [(p["path"], p["sha256"]) for p in manifest_a["partitions"]] == \
           [(p["path"], p["sha256"]) for p in manifest_b["partitions"]]


def test_manifest_carries_provenance_and_refuses_production(tmp_path):
    adapter = build_adapter(tmp_path, ONE_SEASON)
    manifest = corpus.build(adapter, str(tmp_path / "out"), created_at="2026-11-25T00:00:00Z")
    assert manifest["completeness"] == "COMPLETE"
    assert manifest["productionEligible"] is False
    assert manifest["source"]["licence"] == "CC0-1.0"
    assert COMMIT in manifest["source"]["sourceUrl"]
    assert manifest["source"]["permissions"]["verified"]["status"] == "UNVERIFIED"
    assert any("openfootball-date-only-v1" in note for note in manifest["notes"])


def test_build_refuses_a_source_without_research_permission(tmp_path, monkeypatch):
    adapter = build_adapter(tmp_path, ONE_SEASON)
    adapter.meta = type(adapter.meta)(**{**adapter.meta.__dict__,
                                         "permitted": {"research": False}})
    with pytest.raises(ProviderError):
        corpus.build(adapter, str(tmp_path / "out"))


# --------------------------------------------------------------------------- #
# data directory safety
# --------------------------------------------------------------------------- #

def _load_script(name: str):
    path = os.path.join("scripts", name)
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_script_refuses_tracked_output_paths():
    script = _load_script("build_openfootball_corpus.py")
    with pytest.raises(SystemExit):
        script._guard(os.path.join(script.REPO_ROOT, "src", "corpus"))
    with pytest.raises(SystemExit):
        script._guard(os.path.join(script.REPO_ROOT, "docs"))
    assert script._guard(os.path.join(script.REPO_ROOT, "data", "corpus", "x"))


def test_fetch_script_refuses_tracked_output_paths():
    script = _load_script("fetch_openfootball.py")
    with pytest.raises(SystemExit):
        script._guard(os.path.join(script.REPO_ROOT, "config", "sources.json"))


def test_data_directory_is_gitignored():
    ignored = open(".gitignore").read()
    assert "\ndata/" in ignored or ignored.startswith("data/")
