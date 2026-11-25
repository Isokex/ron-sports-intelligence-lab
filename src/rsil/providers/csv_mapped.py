"""Generic CSV adapter driven by a mapping spec.

A spec may DECLARE permissions; it can never VERIFY them. Whatever a spec says
about production rights, this adapter emits an unverified source, because a
file we downloaded cannot grant us rights we do not hold.
"""
import csv
import json

from .base import ProviderResult, SourceMeta, Verification


class CsvMappedProvider:
    is_synthetic = False

    def __init__(self, csv_path, spec_path):
        self.csv_path = csv_path
        with open(spec_path) as fh:
            self.spec = json.load(fh)
        raw = dict(self.spec.get("meta") or {})
        raw.pop("verification", None)   # a spec cannot verify itself
        self.meta = SourceMeta(
            name=str(raw.get("name") or "csv"),
            licence=str(raw.get("licence") or ""),
            licence_url=str(raw.get("licenceUrl") or ""),
            attribution=str(raw.get("attribution") or ""),
            source_url=str(raw.get("sourceUrl") or ""),
            retrieved_at=str(raw.get("retrievedAt") or ""),
            permitted=dict(raw.get("permitted") or {}),
            verification=Verification(status="UNVERIFIED"),
        )
        self.is_synthetic = bool(raw.get("synthetic"))
        self.columns = dict(self.spec.get("columns") or {})
        self.constants = dict(self.spec.get("constants") or {})

    def fetch(self):
        notes = ["permissions declared by the spec; NOT verified"]
        records = []
        with open(self.csv_path, newline="") as fh:
            for row in csv.DictReader(fh):
                mapped = {field: row.get(column)
                          for field, column in self.columns.items()}
                mapped.update(self.constants)
                mapped.setdefault("source_name", self.meta.name)
                records.append(mapped)
        return ProviderResult(records=records, complete=True, meta=self.meta,
                              notes=notes)
