"""OpenFootball adapter: CC0 fixtures and reported final scores.

The source is pinned by commit and by per-file hash, and the adapter refuses to
read anything else. Three things it deliberately does not do:

* guess a score shape. OpenFootball writes ``{"ht": [...], "ft": [...]}``,
  ``{"ft": [...]}`` and bare ``[home, away]`` arrays, sometimes in the same
  file, so every record's shape is inspected and an unrecognised shape is
  rejected with a reason rather than coerced;
* guess a timezone. ``time`` is advisory and never becomes an instant;
* guess a club. Names resolve through the versioned alias map by exact lookup.

Temporal contract (Phase 2A rule 4.2.1): a date-only record derives outcome
availability from the end of the recorded UTC date plus 120 minutes. ``kickoff_utc``
carries the start of the recorded UTC date, which is the earliest plausible
kickoff and therefore the conservative bound for a pre-match cutoff.
"""
from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from ..identity import IdentityError, TeamResolver
from ..schema import match_key
from .base import ProviderError, ProviderResult, SourceMeta

DERIVATION_RULE = "openfootball-date-only-v1"
AVAILABILITY_LAG = timedelta(minutes=120)
DEFAULT_CONFIG = os.path.join("config", "openfootball-sources.json")
DEFAULT_ALIASES = os.path.join("config", "team-aliases-v1.json")


class ScoreFormatError(RuntimeError):
    """A score this adapter will not interpret. Carries a stable code."""

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


def _pair(value, label: str) -> tuple[int, int]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ScoreFormatError("invalid_score_pair", f"{label} must hold two values")
    goals = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            raise ScoreFormatError("invalid_score_value", f"{label} must hold integers")
        if item < 0 or item > 30:
            raise ScoreFormatError("invalid_score_value", f"{label} outside 0..30")
        goals.append(item)
    return goals[0], goals[1]


def normalize_score(score) -> tuple[int, int, int | None, int | None]:
    """Return ``(ft_home, ft_away, ht_home, ht_away)`` or raise.

    Accepted shapes, each seen in real OpenFootball files:

    * ``{"ft": [h, a], "ht": [h, a]}``
    * ``{"ft": [h, a]}``
    * ``[h, a]`` (full time only)

    Anything else raises rather than being guessed at.
    """
    if score is None:
        raise ScoreFormatError("missing_score", "record has no score")
    if isinstance(score, dict):
        unknown = set(score) - {"ft", "ht"}
        if unknown:
            raise ScoreFormatError("unsupported_score_keys",
                                   f"unexpected score keys: {sorted(unknown)}")
        if "ft" not in score:
            raise ScoreFormatError("missing_score", "score object has no ft")
        ft_home, ft_away = _pair(score["ft"], "ft")
        if score.get("ht") is None:
            return ft_home, ft_away, None, None
        ht_home, ht_away = _pair(score["ht"], "ht")
        return ft_home, ft_away, ht_home, ht_away
    if isinstance(score, list):
        ft_home, ft_away = _pair(score, "score")
        return ft_home, ft_away, None, None
    raise ScoreFormatError("unsupported_score_type",
                           f"score is {type(score).__name__}")


def score_format(score) -> str:
    """Stable label describing a record's score shape, for the audit."""
    if isinstance(score, dict):
        return "object:" + ",".join(sorted(score))
    if isinstance(score, list):
        return f"list:{len(score)}"
    return type(score).__name__


def derive_availability(day: str) -> tuple[str, str, dict]:
    """``(source_timestamp, derived_available_at, uncertainty)`` for a date-only row."""
    return (
        f"{day}T00:00:00+00:00",
        f"{(date.fromisoformat(day) + timedelta(days=1)).isoformat()}T02:00:00+00:00",
        {
            "basis": "date_only",
            "earliest": f"{day}T00:00:00+00:00",
            "latest": f"{(date.fromisoformat(day) + timedelta(days=1)).isoformat()}T02:00:00+00:00",
            "rule": DERIVATION_RULE,
        },
    )


@dataclass(frozen=True)
class SourceFile:
    season: str
    path: str
    sha256: str
    records: int
    bytes: int


@dataclass
class OpenFootballAdapter:
    """Reads pinned OpenFootball JSON and maps it onto the canonical schema."""

    source_root: str
    config_path: str = DEFAULT_CONFIG
    aliases_path: str = DEFAULT_ALIASES
    ingested_at: str | None = None
    meta: SourceMeta | None = field(default=None, init=False)
    provenance: list = field(default_factory=list, init=False)
    rejections: list = field(default_factory=list, init=False)
    score_formats: Counter = field(default_factory=Counter, init=False)
    date_anomalies: list = field(default_factory=list, init=False)
    is_synthetic: bool = field(default=False, init=False)

    def __post_init__(self):
        config = self._read_json(self.config_path, "config_unreadable")
        for key in ("repository", "commit", "licence", "competition", "seasons"):
            if not config.get(key):
                raise ProviderError(f"config_missing:{key}")
        if len(str(config["commit"])) != 40:
            raise ProviderError("config_unpinned:commit")
        self.config = config
        self.resolver = TeamResolver.load(self.aliases_path)
        licence = config["licence"]
        commit = config["commit"]
        repo = config["repository"]
        self.files = [SourceFile(season=item["season"], path=item["path"],
                                 sha256=item["sha256"],
                                 records=int(item.get("source_records") or 0),
                                 bytes=int(item.get("bytes") or 0))
                      for item in config["seasons"]]
        self.meta = SourceMeta(
            name="openfootball",
            licence=licence["name"],
            licence_url=licence["url"],
            attribution=licence["attribution"],
            source_url=f"https://github.com/{repo}/tree/{commit}",
            retrieved_at=self.ingested_at or config["retrieved_at"],
            permitted={"research": True, "production_training": False,
                       "redistribution": True},
        )

    @staticmethod
    def _read_json(path: str, code: str):
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except OSError as exc:
            raise ProviderError(f"{code}:{path}:{exc}") from exc
        except json.JSONDecodeError as exc:
            raise ProviderError(f"{code}:{path}:{exc}") from exc

    def _read_season(self, source_file: SourceFile) -> dict:
        path = os.path.join(self.source_root, source_file.path)
        try:
            with open(path, "rb") as fh:
                raw = fh.read()
        except OSError as exc:
            raise ProviderError(f"source_unreadable:{source_file.season}:{exc}") from exc
        digest = hashlib.sha256(raw).hexdigest()
        if digest != source_file.sha256:
            raise ProviderError(
                f"source_hash_mismatch:{source_file.season}:expected "
                f"{source_file.sha256}, got {digest}")
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ProviderError(f"source_invalid_json:{source_file.season}:{exc}") from exc

    @staticmethod
    def _season_opener(matches: list) -> str | None:
        """Earliest date among the source's own opening matchday records.

        Used as a self-consistent lower bound: a league season cannot contain a
        fixture dated before its own opening round. OpenFootball's 2019-20 file
        dates 66 matches 2019-07-xx that are really 2020-07-xx (a year typo), and
        accepting them would make 2020 results look available in July 2019.
        """
        opening = [m.get("date") for m in matches
                   if isinstance(m, dict)
                   and str(m.get("round", "")).strip().lower() == "matchday 1"
                   and isinstance(m.get("date"), str) and m.get("date")]
        if opening:
            return min(opening)
        dates = [m.get("date") for m in matches
                 if isinstance(m, dict) and isinstance(m.get("date"), str)
                 and m.get("date")]
        return min(dates) if dates else None

    def fetch(self) -> ProviderResult:
        competition = self.config["competition"]
        competition_id = competition["competition_id"]
        competition_name = competition.get("name") or competition_id
        rows = []
        for source_file in self.files:
            payload = self._read_season(source_file)
            matches = payload.get("matches")
            if not isinstance(matches, list):
                raise ProviderError(f"source_malformed:{source_file.season}:no matches")
            opener = self._season_opener(matches)
            for index, raw in enumerate(matches):
                row, reason = self._parse(raw, index, source_file, competition_id,
                                          competition_name, opener)
                if row is None:
                    self.rejections.append({"season": source_file.season,
                                            "index": index, "reason": reason})
                    continue
                rows.append(row)
        notes = [
            f"source pinned at {self.config['repository']}@{self.config['commit']}",
            f"licence {self.config['licence']['name']} evidence "
            f"{self.config['licence']['url']}",
            f"team mapping {self.resolver.version}",
            f"temporal rule {DERIVATION_RULE}: date-only records derive outcome "
            "availability from end of recorded UTC date plus 120 minutes",
            "source kickoff times are advisory and never establish a UTC instant",
            f"{len(self.rejections)} source records rejected; see audit",
        ]
        return ProviderResult(records=rows, complete=True, meta=self.meta,
                              notes=notes, observations=[])

    def _parse(self, raw, index: int, source_file: SourceFile,
               competition_id: str, competition_name: str,
               opener: str | None = None):
        if not isinstance(raw, dict):
            return None, "record_not_object"
        day = raw.get("date")
        if not isinstance(day, str) or not day:
            return None, "missing_date"
        try:
            date.fromisoformat(day)
        except ValueError:
            return None, "invalid_date"
        if opener and day < opener:
            self.date_anomalies.append({"season": source_file.season,
                                        "index": index, "date": day,
                                        "opener": opener,
                                        "round": raw.get("round")})
            return None, "date_before_season_opener"
        home_source = raw.get("team1")
        away_source = raw.get("team2")
        if not isinstance(home_source, str) or not isinstance(away_source, str):
            return None, "missing_teams"
        home_id = self.resolver.resolve(home_source)
        if home_id is None:
            return None, f"unknown_team:{home_source}"
        away_id = self.resolver.resolve(away_source)
        if away_id is None:
            return None, f"unknown_team:{away_source}"

        score = raw.get("score")
        self.score_formats[score_format(score)] += 1
        try:
            ft_home, ft_away, ht_home, ht_away = normalize_score(score)
        except ScoreFormatError as exc:
            return None, exc.code

        source_timestamp, available_at, uncertainty = derive_availability(day)
        kickoff = f"{day}T00:00:00+00:00"
        match_id = f"{day}:{home_id}:{away_id}"
        key = match_key(competition_id, source_file.season, match_id)
        row = {
            "competition_id": competition_id,
            "competition_name": competition_name,
            "season": source_file.season,
            "match_id": match_id,
            "match_key": key,
            "kickoff_utc": kickoff,
            "status": "FT",
            "home_team_id": home_id,
            "home_team_name": self.resolver.display_name(home_id),
            "away_team_id": away_id,
            "away_team_name": self.resolver.display_name(away_id),
            "home_goals": ft_home,
            "away_goals": ft_away,
            "ht_home_goals": ht_home,
            "ht_away_goals": ht_away,
            "available_at": available_at,
            "source_name": "openfootball",
            "source_record_id": f"{source_file.season}/{source_file.path}#{index}",
            "source_url": (f"https://github.com/{self.config['repository']}/blob/"
                           f"{self.config['commit']}/{source_file.path}"),
            "ingested_at": self.meta.retrieved_at,
            "is_synthetic": False,
        }
        self.provenance.append({
            "match_key": key,
            "season": source_file.season,
            "source_file": source_file.path,
            "source_sha256": source_file.sha256,
            "source_index": index,
            "source_round": raw.get("round"),
            "source_date": day,
            "source_time": raw.get("time"),
            "source_team_home": home_source,
            "source_team_away": away_source,
            "source_score_raw": score,
            "score_format": score_format(score),
            "source_timestamp": source_timestamp,
            "derived_available_at": available_at,
            "derivation_rule": DERIVATION_RULE,
            "uncertainty": uncertainty,
            "team_mapping_version": self.resolver.version,
        })
        return row, None
