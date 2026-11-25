"""Temporal model: event time versus information availability.

`kickoff_utc` is when the event happened. `available_at` is when a specific
piece of information became known. There is deliberately NO universal ordering
between them: pre-match odds and lineups are known BEFORE kickoff, results and
post-match statistics AFTER it, and corrections whenever they occur.

Two separate questions follow, and they must never share a cutoff:

* FEATURES for a prediction at T may read only records whose `available_at`
  is <= T, and only observation kinds that exist before a match starts.
* LABELS are outcomes. They are eligible once the outcome is available, and
  they are resolved at a label timestamp, never at the prediction timestamp.
"""

from dataclasses import dataclass, field

from .schema import FINISHED, parse_iso

PRE_MATCH_KINDS = frozenset({"pre_match_odds", "pre_match_lineup",
                             "pre_match_team_news"})
POST_MATCH_KINDS = frozenset({"result", "post_match_stats", "correction"})
OBSERVATION_KINDS = PRE_MATCH_KINDS | POST_MATCH_KINDS

MAX_GOALS = 30


class TemporalError(ValueError):
    """A temporal contract was violated. Codes are stable and machine-readable."""


@dataclass(frozen=True)
class Observation:
    match_key: str
    kind: str
    available_at: str
    payload: dict = field(default_factory=dict)
    source_name: str = ""
    source_record_id: str = ""

    def row(self) -> dict:
        return {"match_key": self.match_key, "kind": self.kind,
                "available_at": self.available_at, "payload": self.payload,
                "source_name": self.source_name,
                "source_record_id": self.source_record_id}


def require_timestamp(value, label="timestamp") -> str:
    """Normalised UTC ISO-8601 string, or TemporalError with a stable code."""
    if not isinstance(value, str) or not value.strip():
        raise TemporalError(f"invalid_timestamp:{label}")
    parsed = parse_iso(value)
    if parsed is None:
        raise TemporalError(f"invalid_timestamp:{label}")
    if parsed.tzinfo is None:
        raise TemporalError(f"naive_timestamp:{label}")
    return parsed.isoformat()


def _at(row) -> "object":
    return parse_iso((row or {}).get("available_at"))


def validate_observation(raw) -> tuple:
    """(Observation, None) or (None, reason). Unknown kinds are rejected."""
    if not isinstance(raw, dict):
        return None, "not_a_mapping"
    kind = str(raw.get("kind") or "")
    if kind not in OBSERVATION_KINDS:
        return None, f"unknown_kind:{kind or 'missing'}"
    if not raw.get("match_key"):
        return None, "missing:match_key"
    try:
        stamp = require_timestamp(raw.get("available_at"), "available_at")
    except TemporalError as exc:
        return None, str(exc)
    payload = raw.get("payload") or {}
    if not isinstance(payload, dict):
        return None, "payload_not_a_mapping"
    return Observation(match_key=str(raw["match_key"]), kind=kind,
                       available_at=stamp, payload=dict(payload),
                       source_name=str(raw.get("source_name") or ""),
                       source_record_id=str(raw.get("source_record_id") or "")), None


def visible(records, as_of) -> list:
    """Records whose information was available at or before `as_of`."""
    cutoff = require_timestamp(as_of, "as_of")
    limit = parse_iso(cutoff)
    out = []
    for row in records or []:
        stamp = _at(row)
        if stamp is not None and stamp <= limit:
            out.append(row)
    return out


def temporal_view(matches, observations, as_of) -> dict:
    """Everything known at `as_of`, and how much was withheld."""
    cutoff = require_timestamp(as_of, "as_of")
    limit = parse_iso(cutoff)
    results, observations_out = [], []
    dropped_matches = dropped_obs = 0
    for row in matches or []:
        stamp = _at(row)
        if stamp is not None and stamp <= limit:
            results.append(row)
        else:
            dropped_matches += 1
    for obs in observations or []:
        stamp = _at(obs)
        if stamp is not None and stamp <= limit:
            observations_out.append(obs)
        else:
            dropped_obs += 1
    return {"asOf": cutoff, "results": results,
            "observations": observations_out,
            "excluded": {"results": dropped_matches,
                         "observations": dropped_obs}}


def assert_prematch_timestamp(as_of, kickoff_utc) -> str:
    """The pre-match invariant, in one place so no builder can restate it.

    A prediction timestamp at kickoff is allowed; one after kickoff is not,
    because by then the outcome of this very match may exist.
    """
    cutoff = require_timestamp(as_of, "as_of")
    kickoff = parse_iso(kickoff_utc)
    if kickoff is None:
        raise TemporalError("invalid_timestamp:kickoff_utc")
    if parse_iso(cutoff) > kickoff:
        raise TemporalError("prediction_after_kickoff")
    return cutoff


def prematch_feature_inputs(match, history, observations, as_of) -> dict:
    """PRE-MATCH, leakage-safe inputs for one match at one prediction time.

    `as_of` must not be later than the target kickoff. Only pre-match
    observation kinds are admitted: a `result` or `post_match_stats` record is
    refused even when its timestamp falsely claims it existed before kickoff.
    Everything withheld is counted, never hidden.
    """
    cutoff = assert_prematch_timestamp(as_of, match.get("kickoff_utc"))
    limit = parse_iso(cutoff)
    key = match.get("match_key")
    kickoff = parse_iso(match.get("kickoff_utc"))

    usable_history, dropped_history = [], 0
    for past in history or []:
        if past.get("match_key") == key:
            continue
        stamp = _at(past)
        past_kickoff = parse_iso(past.get("kickoff_utc"))
        if stamp is None or stamp > limit or past_kickoff is None \
                or past_kickoff >= kickoff:
            dropped_history += 1
            continue
        usable_history.append(past)

    usable_obs, dropped_obs, dropped_kind = [], 0, 0
    for obs in observations or []:
        if obs.get("match_key") != key:
            continue
        if str(obs.get("kind") or "") not in PRE_MATCH_KINDS:
            dropped_kind += 1
            continue
        stamp = _at(obs)
        if stamp is None or stamp > limit:
            dropped_obs += 1
            continue
        usable_obs.append(obs)

    return {"match_key": key, "kickoff_utc": match.get("kickoff_utc"),
            "asOf": cutoff, "observations": usable_obs,
            "history": usable_history,
            # Timestamp-only: True when the source reports an outcome time at
            # or before the cutoff. The corpus permits an outcome timestamp
            # before kickoff (a warning, not a rejection), so this CAN be True
            # pre-match. It is never proof that a valid label exists;
            # training_labels is the sole authority on label eligibility.
            "label_visible": (lambda st: st is not None and st <= limit)(
                _at(match)),
            "excluded": {"observations": dropped_obs,
                         "post_match_observations": dropped_kind,
                         "history": dropped_history}}


feature_inputs = prematch_feature_inputs


def label_eligible(row, limit) -> bool:
    """A label needs a finished match, two valid final scores, and an outcome
    time at or before `limit`. Anything less is a gap, not a label."""
    stamp = _at(row)
    if stamp is None or stamp > limit:
        return False
    if str(row.get("status") or "").upper() not in FINISHED:
        return False
    for name in ("home_goals", "away_goals"):
        value = row.get(name)
        if isinstance(value, bool) or not isinstance(value, int):
            return False
        if value < 0 or value > MAX_GOALS:
            return False
    return True


def training_labels(matches, as_of) -> list:
    """Historical outcomes usable as labels at `as_of`.

    Post-match information is legitimate here: a result becomes a label once
    its outcome time has passed. There is no kickoff ceiling, because labels
    are not features. Unfinished, scoreless or impossible results are dropped.
    """
    cutoff = require_timestamp(as_of, "as_of")
    limit = parse_iso(cutoff)
    return [row for row in (matches or []) if label_eligible(row, limit)]


def training_example(match, history, observations, as_of,
                     label_as_of=None) -> dict:
    """One reproducible training example: pre-match features plus the label.

    `as_of` is the PREDICTION timestamp and must not pass kickoff; the same
    guard as the feature path is used, so a dataset builder inherits the
    invariant instead of restating it. The label is resolved separately at
    `label_as_of` (default `as_of`), which is normally the dataset build time.
    """
    features = prematch_feature_inputs(match, history, observations, as_of)
    labels = [row for row in training_labels([match], label_as_of or as_of)
              if row.get("match_key") == match.get("match_key")]
    features["label"] = ({"home_goals": labels[0].get("home_goals"),
                          "away_goals": labels[0].get("away_goals")}
                         if labels else None)
    # True only when an eligible label was attached by training_labels.
    features["label_visible"] = bool(labels)
    return features


def assert_no_leakage(rows, as_of) -> None:
    """Fail loudly if any supplied row was not available at `as_of`."""
    cutoff = require_timestamp(as_of, "as_of")
    limit = parse_iso(cutoff)
    for row in rows or []:
        stamp = _at(row)
        if stamp is None or stamp > limit:
            raise TemporalError(
                f"leakage:{row.get('match_key') or row.get('kind')}")
