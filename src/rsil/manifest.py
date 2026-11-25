"""Content-hashed dataset manifests.

The manifest is the contract: it states what was read, from which source,
under which licence, how complete the scan was, and the hash of the exact
rows produced. Two runs over unchanged source data must produce the same
contentHash.
"""
import hashlib
import json

from . import SCHEMA_VERSION, TRANSFORM_VERSION


def canonical_row(row: dict) -> str:
    return json.dumps(row, sort_keys=True, separators=(",", ":"), default=str)


def content_hash(rows: list) -> str:
    digest = hashlib.sha256()
    for row in sorted(rows, key=lambda r: str(r.get("match_id"))):
        digest.update(canonical_row(row).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(meta: dict, report, partitions: list, rows: list,
                   complete: bool, created_at: str, notes=None) -> dict:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "transformVersion": TRANSFORM_VERSION,
        "createdAt": created_at,
        "completeness": "COMPLETE" if complete else "PARTIAL",
        "suitableForProductionTraining": False,
        "source": meta,
        "counts": report.counts(),
        "rejectionReasons": report.reasons(),
        "conflicts": report.conflicts,
        "partitions": partitions,
        "contentHash": content_hash(rows),
        "notes": list(notes or []),
    }


def write_manifest(out_dir: str, manifest: dict) -> str:
    path = f"{out_dir}/manifest.json"
    with open(path, "w") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return path
