"""Temporal model: event time versus information availability.

`kickoff_utc` is when the event happened. `available_at` is when one specific
piece of information became known to the lab. There is deliberately NO
universal ordering between them:

* pre-match odds, confirmed lineups and team news become available BEFORE kickoff;
* final results and post-match statistics become available AFTER it;
* corrections and late amendments become available whenever the source
  publishes them, which can be days later.

A match-level row cannot honestly carry one availability timestamp for all of
those, so match-level `available_at` means "the time the OUTCOME became
available" and everything else is expressed as an `Observation` with its own
`available_at`.

The only rule that matters for training is the feature rule: features for a
prediction made at time T may read only records whose `available_at` is less
than or equal to T. Everything else is leakage.
"""
from dataclasses import dataclass, field

from .schema import parse_iso

PRE_MATCH_KINDS = frozenset({"pre_match_odds", "pre_match_lineup",
                             "pre_match_team_news"})
POST_MATCH_KINDS = frozenset({"result", "post_match_stats", "correction"})
OBSERVATION_KINDS = PRE_MATCH_KINDS | POST_MATCH_KINDS

OBSERVATION_FIELDS = ("match_key", "kind", "available_at", "payload",
                      "source_name", "source_record_id")


class TemporalError(ValueError):
    """Raised when a temporal request is malformed (for example a naive time)."""


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
                "available_at": self.available_at,
                "payload": dict(self.payload),
                "source_name": self.source_name,
                "source_record_id": self.source_record_id}


def validate_observation(raw) -> tuple:
    """Return (Observation, None) or (None, machine_readable_reason)."""
    if not isinstance(raw, dict):
        return None, "not_a_mapping"
    for required in ("match_key", "kind", "available_at"):
        if raw.get(required) in (None, ""):
            return None, f"missing:{required}"
    kind = str(raw["kind"])
    if kind not in OBSERVATION_KINDS:
        return None, f"unknown_kind:{kind}"
    try:
        available_at = require_timestamp(raw["available_at"], "available_at")
    except TemporalError as exc:
        return None, str(exc)
    payload = raw.get("payload") or {}
    if not isinstance(payload, dict):
        return None, "payload_not_a_mapping"
    return Observation(match_key=str(raw["match_key"]), kind=kind,
                       available_at=available_at, payload=payload,
                       source_name=str(raw.get("source_name") or ""),
                       source_record_id=str(raw.get("source_record_id") or "")), None


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
    return parse_iso(row.get("available_at"))


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
    """Split a corpus at one prediction timestamp.

    `results` are matches whose outcome was known by `as_of`. `observations`
    are pre/post-match facts known by `as_of`. `excluded` counts what was
    withheld, so a caller can never mistake a small view for a full corpus.
    """
    cutoff = require_timestamp(as_of, "as_of")
    limit = parse_iso(cutoff)
    known_matches, unknown_matches = [], []
    for match in matches or []:
        stamp = _at(match)
        if stamp is not None and stamp <= limit:
            known_matches.append(match)
        else:
            unknown_matches.append(match)
    obs_visible, obs_hidden = [], []
    for obs in observations or []:
        stamp = _at(obs)
        if stamp is not None and stamp <= limit:
            obs_visible.append(obs)
        else:
            obs_hidden.append(obs)
    return {"asOf": cutoff, "results": known_matches,
            "observations": obs_visible,
            "excluded": {"results": len(unknown_matches),
                         "observations": len(obs_hidden)}}


def assert_prematch_timestamp(as_of, kickoff_utc) -> str:
    """The one pre-match invariant: a prediction timestamp may not be later
    than the target kickoff.

    Exported deliberately: the training dataset builder must call this, not
    re-implement it, so features and datasets cannot drift apart.
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

    This function is pre-match only: `as_of` must not be later than the target
    kickoff (see `assert_prematch_timestamp`). Outcomes are labels, not
    features, and belong in `training_labels`.

    `history` may contain anything. Only finished matches whose outcome was
    available by `as_of` AND which kicked off before this match are used, and
    only observations with `available_at <= as_of` are returned. The counts of
    what was dropped are returned with the data, never hidden.
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

    usable_obs, dropped_obs = [], 0
    for obs in observations or []:
        if obs.get("match_key") != key:
            continue
        stamp = _at(obs)
        if stamp is None or stamp > limit:
            dropped_obs += 1
            continue
        usable_obs.append(obs)

    label_stamp = _at(match)
    return {"match_key": key, "kickoff_utc": match.get("kickoff_utc"),
            "asOf": cutoff, "observations": usable_obs,
            "history": usable_history,
            "label_visible": label_stamp is not None and label_stamp <= limit,
            "excluded": {"observations": dropped_obs,
                         "history": dropped_history}}


def training_labels(matches, as_of) -> list:
    """Historical outcomes usable as labels at `as_of`.

    Post-match information is legitimate here: a result becomes a label once
    its outcome time has passed. There is no kickoff ceiling, because labels
    are not features.
    """
    cutoff = require_timestamp(as_of, "as_of")
    limit = parse_iso(cutoff)
    out = []
    for row in matches or []:
        stamp = _at(row)
        if stamp is not None and stamp <= limit:
            out.append(row)
    return out


def training_example(match, history, observations, as_of,
                     label_as_of=None) -> dict:
    """One reproducible training example: pre-match features plus the label.

    `as_of` is the PREDICTION timestamp and must not pass kickoff; the same
    guard as the feature path is used, so a dataset builder inherits the
    invariant instead of restating it. The label is resolved separately at
    `label_as_of` (default `as_of`), which is normally the dataset build time,
    because an outcome is only a label once it has happened.
    """
    features = prematch_feature_inputs(match, history, observations, as_of)
    labels = [m for m in training_labels([match], label_as_of or as_of)
              if m.get("match_key") == match.get("match_key")]
    return {"features": features,
            "label": labels[0] if labels else None,
            "label_visible": bool(labels)}


# Backwards-compatible name; pre-match semantics are identical.
feature_inputs = prematch_feature_inputs


def assert_no_leakage(rows, as_of) -> None:
    """Hard guard: raise if any supplied record is from the future."""
    cutoff = require_timestamp(as_of, "as_of")
    limit = parse_iso(cutoff)
    for row in rows or []:
        stamp = _at(row)
        if stamp is None or stamp > limit:
            raise TemporalError(
                f"leakage: record available_at={row.get('available_at')!r} "
                f"is after as_of={cutoff}")
