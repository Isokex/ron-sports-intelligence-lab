"""Corpus build: provider -> validate -> partitioned Parquet -> manifest."""
import os
from datetime import datetime, timezone

import pyarrow as pa
import pyarrow.parquet as pq

from .manifest import build_manifest, file_sha256, write_manifest
from .providers import ensure_research_allowed
from .quality import validate
from .schema import FIELDS

from .schema import BOOL_FIELDS, FLOAT_FIELDS, INT_FIELDS  # noqa: E402


def _arrow_type(field: str):
    if field in BOOL_FIELDS:
        return pa.bool_()
    if field in FLOAT_FIELDS:
        return pa.float64()
    if field in INT_FIELDS:
        return pa.int64()
    return pa.string()


ARROW_SCHEMA = pa.schema([(f, _arrow_type(f)) for f in FIELDS])


def _write_partitions(rows: list, out_dir: str) -> list:
    grouped = {}
    for row in rows:
        key = (str(row["competition_id"]), str(row["season"]))
        grouped.setdefault(key, []).append(row)
    partitions = []
    for (comp, season), group in sorted(grouped.items()):
        rel = f"partitions/competition_id={comp}/season={season}/part-00000.parquet"
        path = os.path.join(out_dir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        ordered = sorted(group, key=lambda r: str(r["match_id"]))
        table = pa.Table.from_pylist(
            [{f: r.get(f) for f in FIELDS} for r in ordered], schema=ARROW_SCHEMA)
        pq.write_table(table, path, compression="snappy")
        partitions.append({"path": rel, "rows": len(ordered),
                           "sha256": file_sha256(path)})
    return partitions


def build(provider, out_dir: str, created_at: str | None = None) -> dict:
    ensure_research_allowed(provider.meta)
    created_at = created_at or datetime.now(timezone.utc).isoformat()
    result = provider.fetch()
    report = validate(result.records, source_name=result.meta.name,
                      ingested_at=result.meta.retrieved_at,
                      is_synthetic=getattr(provider, "is_synthetic", False))
    rows = [rec.row() for rec in report.accepted]
    os.makedirs(out_dir, exist_ok=True)
    partitions = _write_partitions(rows, out_dir)
    manifest = build_manifest(result.meta.as_dict(), report, partitions, rows,
                              complete=result.complete, created_at=created_at,
                              notes=result.notes)
    write_manifest(out_dir, manifest)
    return manifest
