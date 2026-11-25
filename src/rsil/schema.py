"""Canonical match schema (rsil-match-v2).

One row per match, keyed by `match_key` = competition_id|season|match_id, so
identical match ids in different competitions or sources stay distinct.

`kickoff_utc` is the event time. `available_at` on a match row is the time the
OUTCOME became available; per-field availability (odds, lineups, corrections)
lives in observations, because one timestamp cannot honestly describe both
pre-match and post-match information. See `rsil.temporal`.
"""
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

from . import SCHEMA_VERSION

FIELDS = (
    "competition_id", "competition_name", "season", "match_id", "match_key",
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

TIMESTAMP_FIELDS = ("kickoff_utc", "available_at", "odds_captured_at",
                    "ingested_at")

FINISHED = {"FT", "AET", "PEN", "FINISHED", "ENDED"}

INT_FIELDS = {"home_goals", "away_goals", "ht_home_goals", "ht_away_goals",
              "shots_home", "shots_away", "shots_on_target_home",
              "shots_on_target_away"}
FLOAT_FIELDS = {"xg_home", "xg_away", "odds_home", "odds_draw", "odds_away"}
BOOL_FIELDS = {"is_synthetic"}


class CoercionError(ValueError):
    """A value that cannot be represented without loss. Carries a stable code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def parse_iso(value):
    """Parse to an aware datetime, or None. Never invents a timezone."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed


def normalize_timestamp(value) -> str:
    """UTC ISO-8601 string. Naive or unparseable values are rejected, not guessed."""
    if not isinstance(value, str) or not value.strip():
        raise CoercionError("invalid_timestamp")
    parsed = parse_iso(value)
    if parsed is None:
        raise CoercionError("invalid_timestamp")
    if parsed.tzinfo is None:
        raise CoercionError("naive_timestamp")
    return parsed.astimezone(timezone.utc).isoformat()


def match_key(competition_id, season, match_id) -> str:
    """Stable identity: the same match id in two competitions is two matches."""
    return f"{competition_id}|{season}|{match_id}"


def coerce(field: str, value):
    """Convert by declared field type, refusing any lossy conversion."""
    if value is None or value == "":
        return None
    if field in INT_FIELDS:
        if isinstance(value, bool):
            raise CoercionError("not_an_integer")
        if isinstance(value, int):
            return value
        try:
            number = float(str(value).strip()) if not isinstance(value, float) \
                else value
        except (TypeError, ValueError):
            raise CoercionError("not_an_integer")
        if number != int(number):
            raise CoercionError("not_an_integer")
        return int(number)
    if field in FLOAT_FIELDS:
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise CoercionError("not_a_number")
        if number != number or number in (float("inf"), float("-inf")):
            raise CoercionError("not_a_number")
        return number
    return value


@dataclass(frozen=True)
class MatchRecord:
    competition_id: str
    competition_name: str
    season: str
    match_id: str
    match_key: str
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

    Returns (MatchRecord, None) or (None, reason). Missing required values and
    lossy conversions are rejected with a machine-readable reason: nothing is
    defaulted, truncated or guessed.
    """
    if not isinstance(raw, dict):
        return None, "not_a_mapping"
    missing = [f for f in REQUIRED if raw.get(f) in (None, "")]
    if missing:
        return None, "missing:" + ",".join(missing)
    values = {}
    for field in FIELDS:
        try:
            values[field] = coerce(field, raw.get(field))
        except CoercionError as exc:
            return None, f"{exc.code}:{field}"
    for field in TIMESTAMP_FIELDS:
        if values.get(field) is None:
            continue
        try:
            values[field] = normalize_timestamp(values[field])
        except CoercionError as exc:
            return None, f"{exc.code}:{field}"
    if values.get("ingested_at") is None:
        # Deterministic fallback: information cannot be ingested before it
        # existed. Using a clock here would make reruns non-reproducible.
        try:
            values["ingested_at"] = (normalize_timestamp(ingested_at)
                                     if ingested_at
                                     else values["available_at"])
        except CoercionError as exc:
            return None, f"{exc.code}:ingested_at"
    values["source_name"] = source_name
    values["is_synthetic"] = bool(raw.get("is_synthetic", is_synthetic))
    values["season"] = str(values["season"])
    values["match_id"] = str(values["match_id"])
    values["match_key"] = match_key(values["competition_id"], values["season"],
                                    values["match_id"])
    return MatchRecord(**values), None
