"""Canonical match schema (rsil-match-v1).

One row per match. Every row carries event time (kickoff_utc) and information
availability (available_at): the leakage contract depends on telling them apart.
"""
from dataclasses import dataclass, asdict

from . import SCHEMA_VERSION

FIELDS = (
    "competition_id", "competition_name", "season", "match_id",
    "kickoff_utc", "status",
    "home_team_id", "home_team_name", "away_team_id", "away_team_name",
    "home_goals", "away_goals", "ht_home_goals", "ht_away_goals",
    "shots_home", "shots_away", "shots_on_target_home", "shots_on_target_away",
    "xg_home", "xg_away",
    "odds_home", "odds_draw", "odds_away", "odds_captured_at",
    "available_at", "source_name", "source_record_id", "source_url",
    "ingested_at", "is_synthetic",
)

REQUIRED = ("competition_id", "season", "match_id", "kickoff_utc",
            "home_team_name", "away_team_name", "available_at", "source_name")

FINISHED = {"FT", "AET", "PEN", "FINISHED", "ENDED"}

INT_FIELDS = {"home_goals", "away_goals", "ht_home_goals", "ht_away_goals",
              "shots_home", "shots_away", "shots_on_target_home",
              "shots_on_target_away"}
FLOAT_FIELDS = {"xg_home", "xg_away", "odds_home", "odds_draw", "odds_away"}
BOOL_FIELDS = {"is_synthetic"}


def coerce(field: str, value):
    """Tabular sources hand us strings. Convert by declared field type."""
    if value is None or value == "":
        return None
    try:
        if field in INT_FIELDS:
            return int(float(value))
        if field in FLOAT_FIELDS:
            return float(value)
    except (TypeError, ValueError):
        return None
    return value


@dataclass(frozen=True)
class MatchRecord:
    competition_id: str
    competition_name: str
    season: str
    match_id: str
    kickoff_utc: str
    status: str
    home_team_id: str
    home_team_name: str
    away_team_id: str
    away_team_name: str
    home_goals: int | None
    away_goals: int | None
    ht_home_goals: int | None
    ht_away_goals: int | None
    shots_home: int | None
    shots_away: int | None
    shots_on_target_home: int | None
    shots_on_target_away: int | None
    xg_home: float | None
    xg_away: float | None
    odds_home: float | None
    odds_draw: float | None
    odds_away: float | None
    odds_captured_at: str | None
    available_at: str
    source_name: str
    source_record_id: str
    source_url: str
    ingested_at: str
    is_synthetic: bool

    def row(self) -> dict:
        return asdict(self)


def record_from_mapping(raw: dict, source_name: str, ingested_at: str,
                        is_synthetic: bool = False):
    """Map an arbitrary provider row onto the canonical schema.

    Returns (MatchRecord, None) or (None, reason). Never guesses a missing
    required value: an unmappable row is rejected with a reason, not defaulted.
    """
    if not isinstance(raw, dict):
        return None, "not_a_mapping"
    missing = [f for f in REQUIRED if raw.get(f) in (None, "")]
    if missing:
        return None, "missing:" + ",".join(missing)
    values = {f: coerce(f, raw.get(f)) for f in FIELDS}
    values["source_name"] = source_name
    values["ingested_at"] = ingested_at
    values["is_synthetic"] = bool(raw.get("is_synthetic", is_synthetic))
    values["season"] = str(values["season"])
    values["match_id"] = str(values["match_id"])
    return MatchRecord(**values), None
