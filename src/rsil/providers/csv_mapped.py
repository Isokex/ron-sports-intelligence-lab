"""Generic CSV adapter driven by a mapping spec.

Any source with a stable tabular export can be added without touching corpus
code: write a JSON spec that maps its columns onto the canonical fields and
declare the licence. Nothing about a provider is hard-coded here.
"""
import csv
import json

from .base import ProviderError, ProviderResult, SourceMeta


class CsvMappedProvider:
    def __init__(self, csv_path: str, spec_path: str):
        self.csv_path = csv_path
        with open(spec_path) as fh:
            self.spec = json.load(fh)
        meta = self.spec.get("meta") or {}
        self.columns = self.spec.get("columns") or {}
        self.constants = self.spec.get("constants") or {}
        self.meta = SourceMeta(
            name=meta.get("name", "csv"),
            licence=meta.get("licence", "UNKNOWN"),
            licence_url=meta.get("licenceUrl", ""),
            attribution=meta.get("attribution", ""),
            source_url=meta.get("sourceUrl", ""),
            retrieved_at=meta.get("retrievedAt", ""),
            permitted=meta.get("permitted", {}),
        )
        self.is_synthetic = bool(meta.get("synthetic", False))
        self.ingested_at = meta.get("retrievedAt", "")

    def fetch(self) -> ProviderResult:
        try:
            with open(self.csv_path, newline="") as fh:
                rows = list(csv.DictReader(fh))
        except OSError as exc:
            raise ProviderError(f"csv read failed: {type(exc).__name__}") from exc
        records = []
        for row in rows:
            mapped = {}
            for field, column in self.columns.items():
                value = row.get(column)
                mapped[field] = value if value not in ("", None) else None
            for field, value in self.constants.items():
                mapped.setdefault(field, value)
            mapped["source_name"] = self.meta.name
            mapped["ingested_at"] = self.ingested_at
            mapped["is_synthetic"] = self.is_synthetic
            records.append(mapped)
        complete = bool(self.spec.get("complete", True))
        return ProviderResult(records=records, complete=complete, meta=self.meta)
