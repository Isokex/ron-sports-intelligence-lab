"""Provider adapter contract and licensing metadata.

Permissions come in two flavours and are never conflated:

* `declared`   what the source or a CSV spec SAYS is allowed (a claim);
* `verified`   a human's recorded approval, with reviewer, date, scope and
               evidence reference.

A generic adapter cannot grant itself production rights: `CsvMappedProvider`
always emits `verified.status = UNVERIFIED`, whatever its spec claims.
"""
from dataclasses import dataclass, field
from typing import Protocol

PERMITTED_KEYS = ("research", "production_training", "redistribution")


class ProviderError(RuntimeError):
    """A source could not be read. Never downgraded to an empty result."""


@dataclass(frozen=True)
class Verification:
    """Human evidence that a source may be used for a given scope."""
    status: str = "UNVERIFIED"      # APPROVED | REJECTED | UNVERIFIED
    by: str = ""
    at: str = ""
    scope: str = ""
    evidence_url: str = ""

    def as_dict(self) -> dict:
        return {"status": self.status, "by": self.by, "at": self.at,
                "scope": self.scope, "evidenceUrl": self.evidence_url}


@dataclass(frozen=True)
class SourceMeta:
    name: str
    licence: str
    licence_url: str
    attribution: str
    source_url: str
    retrieved_at: str
    permitted: dict
    verification: Verification = field(default_factory=Verification)

    def as_dict(self) -> dict:
        declared = {k: bool(self.permitted.get(k)) for k in PERMITTED_KEYS}
        return {"name": self.name, "licence": self.licence,
                "licenceUrl": self.licence_url,
                "attribution": self.attribution,
                "sourceUrl": self.source_url,
                "retrievedAt": self.retrieved_at,
                "permissions": {"declared": declared,
                                "verified": self.verification.as_dict()}}


@dataclass
class ProviderResult:
    records: list
    complete: bool
    meta: SourceMeta
    notes: list = field(default_factory=list)
    observations: list = field(default_factory=list)


class ProviderAdapter(Protocol):
    meta: SourceMeta

    def fetch(self) -> ProviderResult: ...


def ensure_research_allowed(meta: SourceMeta) -> None:
    """Refuse a source that does not permit research use. Fail closed."""
    if not meta.permitted.get("research"):
        raise ProviderError(
            f"source {meta.name!r} does not permit research use; "
            "obtain written permission or use a permitted source")


def ensure_production_allowed(meta: SourceMeta) -> None:
    """Refuse production use without a recorded human approval."""
    ensure_research_allowed(meta)
    if not meta.permitted.get("production_training"):
        raise ProviderError(
            f"source {meta.name!r} does not declare production-training rights")
    if meta.verification.status != "APPROVED" or not meta.verification.by:
        raise ProviderError(
            f"source {meta.name!r} has no recorded verification; a declared "
            "permission is a claim, not a right")
