"""Corpus build: provider -> validate -> partitioned Parquet -> manifest.

Deterministic throughout: rows are ordered by `match_key`, partitions by
(competition, season), and the manifest hash covers schema and transform
versions, so an unchanged source at unchanged versions produces byte-identical
output and an identical hash.

Observations (pre-match odds/lineups, results, post-match stats, corrections)
are written as their own table, because one match-level availability timestamp
cannot describe them honestly.
"""
import json
import os
from datetime import datetime, timezone

import pyarrow as pa
import pyarrow.parquet as pq

from .manifest import build_manifest, file_sha256, write_manifest
from .providers import ensure_research_allowed
from .quality import validate, validate_observations
from .schema import BOOL_FIELDS, FIELDS, FLOAT_FIELDS, INT_FIELDS

OBSERVATION_SCHEMA = pa.schema([
    ("match_key", pa.string()), ("kind", pa.string()),
    ("available_at", pa.string()), ("source_name", pa.string()),
    ("source_record_id", pa.string()), ("payload_json", pa.string()),
])


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
        ordered = sorted(group, key=lambda r: str(r["match_key"]))
        table = pa.Table.from_pylist(
            [{f: r.get(f) for f in FIELDS} for r in ordered], schema=ARROW_SCHEMA)
        pq.write_table(table, path, compression="snappy")
        partitions.append({"path": rel, "rows": len(ordered),
                           "sha256": file_sha256(path)})
    return partitions


def _write_observations(observations: list, out_dir: str) -> dict:
    if not observations:
        return {"path": None, "rows": 0, "sha256": None}
    rel = "partitions/observations/part-00000.parquet"
    path = os.path.join(out_dir, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    ordered = sorted(observations,
                     key=lambda o: (o.match_key, o.available_at, o.kind))
    table = pa.Table.from_pylist(
        [{"match_key": o.match_key, "kind": o.kind,
          "available_at": o.available_at, "source_name": o.source_name,
          "source_record_id": o.source_record_id,
          "payload_json": json.dumps(o.payload, sort_keys=True)} for o in ordered],
        schema=OBSERVATION_SCHEMA)
    pq.write_table(table, path, compression="snappy")
    return {"path": rel, "rows": len(ordered), "sha256": file_sha256(path)}


def build(provider, out_dir: str, created_at: str | None = None) -> dict:
    ensure_research_allowed(provider.meta)
    created_at = created_at or datetime.now(timezone.utc).isoformat()
    result = provider.fetch()
    report = validate(result.records, source_name=result.meta.name,
                      ingested_at=result.meta.retrieved_at,
                      is_synthetic=getattr(provider, "is_synthetic", False))
    obs_report = validate_observations(getattr(result, "observations", []) or [])
    rows = [rec.row() for rec in report.accepted]
    os.makedirs(out_dir, exist_ok=True)
    partitions = _write_partitions(rows, out_dir)
    obs_partition = _write_observations(obs_report["accepted"], out_dir)
    manifest = build_manifest(
        result.meta.as_dict(), report, partitions, rows,
        complete=bool(result.complete), created_at=created_at,
        notes=result.notes, observations=obs_report["counts"])
    manifest["observationPartition"] = obs_partition
    manifest["observationRejectionReasons"] = obs_report["reasons"]
    write_manifest(out_dir, manifest)
    return manifest
