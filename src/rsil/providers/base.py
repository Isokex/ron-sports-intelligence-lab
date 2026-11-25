"""Provider adapter contract and licensing metadata."""
from dataclasses import dataclass, field
from typing import Protocol

PERMITTED_KEYS = ("research", "production_training", "redistribution")


class ProviderError(RuntimeError):
    """A source could not be read. Never downgraded to an empty result."""


@dataclass(frozen=True)
class SourceMeta:
    name: str
    licence: str
    licence_url: str
    attribution: str
    source_url: str
    retrieved_at: str
    permitted: dict

    def as_dict(self) -> dict:
        permitted = {k: bool(self.permitted.get(k)) for k in PERMITTED_KEYS}
        return {"name": self.name, "licence": self.licence,
                "licenceUrl": self.licence_url,
                "attribution": self.attribution,
                "sourceUrl": self.source_url,
                "retrievedAt": self.retrieved_at,
                "permitted": permitted}


@dataclass
class ProviderResult:
    records: list
    complete: bool
    meta: SourceMeta
    notes: list = field(default_factory=list)


class ProviderAdapter(Protocol):
    meta: SourceMeta

    def fetch(self) -> ProviderResult: ...


def ensure_research_allowed(meta: SourceMeta) -> None:
    """Refuse a source that does not permit research use. Fail closed."""
    if not meta.permitted.get("research"):
        raise ProviderError(
            f"source {meta.name!r} does not permit research use; "
            "obtain written permission or use a permitted source")
