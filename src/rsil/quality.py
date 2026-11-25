"""Validation, duplicate detection and conflict handling.

Findings are data: every rejected or excluded row carries a machine-readable
reason. A validation pass never turns a failure into an empty success.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .schema import FINISHED, REQUIRED, record_from_mapping

ERROR, WARNING = "ERROR", "WARNING"


def parse_iso(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@dataclass
class Finding:
    code: str
    severity: str
    match_id: str
    detail: str = ""


@dataclass
class QualityReport:
    accepted: list = field(default_factory=list)
    rejected: list = field(default_factory=list)
    duplicates: int = 0
    conflicts: list = field(default_factory=list)
    findings: list = field(default_factory=list)

    def counts(self) -> dict:
        return {"accepted": len(self.accepted), "rejected": len(self.rejected),
                "duplicates": self.duplicates, "conflicts": len(self.conflicts),
                "errors": sum(1 for f in self.findings if f.severity == ERROR),
                "warnings": sum(1 for f in self.findings
                                if f.severity == WARNING)}

    def reasons(self) -> dict:
        out = {}
        for reason in [r[1] for r in self.rejected]:
            out[reason] = out.get(reason, 0) + 1
        return out


def _check(rec):
    """Row-level rules. Returns a list of Findings (ERROR blocks acceptance)."""
    out = []
    mid = rec.match_id
    kickoff = parse_iso(rec.kickoff_utc)
    available = parse_iso(rec.available_at)
    if kickoff is None:
        out.append(Finding("invalid_kickoff", ERROR, mid, rec.kickoff_utc or ""))
    if available is None:
        out.append(Finding("invalid_available_at", ERROR, mid,
                           rec.available_at or ""))
    if kickoff and available and available < kickoff:
        out.append(Finding("available_before_kickoff", ERROR, mid,
                           "information cannot be known before the event"))
    if rec.home_team_name and rec.home_team_name == rec.away_team_name:
        out.append(Finding("self_match", ERROR, mid, rec.home_team_name))
    for label, value in (("home_goals", rec.home_goals),
                         ("away_goals", rec.away_goals)):
        if value is not None and (value < 0 or value > 30):
            out.append(Finding("impossible_score", ERROR, mid, f"{label}={value}"))
    has_score = rec.home_goals is not None and rec.away_goals is not None
    if has_score and (rec.status or "").upper() not in FINISHED:
        out.append(Finding("score_on_unfinished_match", ERROR, mid, rec.status or ""))
    for label, value in (("xg_home", rec.xg_home), ("xg_away", rec.xg_away)):
        if value is not None and (value < 0 or value > 15):
            out.append(Finding("invalid_xg", ERROR, mid, f"{label}={value}"))
    for label, value in (("odds_home", rec.odds_home),
                         ("odds_draw", rec.odds_draw),
                         ("odds_away", rec.odds_away)):
        if value is not None and (value <= 1.0 or value > 1000):
            out.append(Finding("invalid_odds", ERROR, mid, f"{label}={value}"))
    if rec.odds_home is not None and not rec.odds_captured_at:
        out.append(Finding("odds_without_capture_time", WARNING, mid, ""))
    if not rec.competition_name:
        out.append(Finding("missing_competition_name", WARNING, mid, ""))
    return out


def _result_of(rec):
    return (rec.home_goals, rec.away_goals, (rec.status or "").upper())


def validate(records, source_name="unknown", ingested_at="", is_synthetic=False):
    """Map, check and de-duplicate. Order is preserved; first write wins."""
    report = QualityReport()
    seen = {}
    for raw in records:
        rec, reason = record_from_mapping(raw, source_name, ingested_at,
                                          is_synthetic)
        if rec is None:
            report.rejected.append((raw, reason))
            continue
        findings = _check(rec)
        blocking = [f for f in findings if f.severity == ERROR]
        report.findings.extend(findings)
        if blocking:
            report.rejected.append((raw, blocking[0].code))
            continue
        prior = seen.get(rec.match_id)
        if prior is not None:
            if _result_of(prior) == _result_of(rec):
                report.duplicates += 1
            else:
                report.conflicts.append({"match_id": rec.match_id,
                                         "kept": list(_result_of(prior)),
                                         "seen": list(_result_of(rec))})
                report.findings.append(Finding(
                    "conflicting_result", ERROR, rec.match_id,
                    "first observation kept, later one recorded"))
            continue
        seen[rec.match_id] = rec
        report.accepted.append(rec)
    return report


__all__ = ["ERROR", "WARNING", "Finding", "QualityReport", "parse_iso",
           "validate", "REQUIRED"]
