"""Content-hashed dataset manifests.

The manifest is the contract: what was read, from which source, under which
declared AND verified permissions, how complete the scan was, and the hash of
the exact rows produced.

Reproducibility: the hash covers the rows in canonical identity order plus the
schema and transform versions, so identical inputs at identical versions give
an identical hash, and any version change necessarily changes it.
"""
import hashlib
import json

from . import SCHEMA_VERSION, TRANSFORM_VERSION

DECLARED_ONLY = "DECLARED_ONLY"
APPROVED = "APPROVED"
REJECTED = "REJECTED"
UNVERIFIED = "UNVERIFIED"


def canonical_row(row: dict) -> str:
    return json.dumps(row, sort_keys=True, separators=(",", ":"), default=str)


def content_hash(rows: list, schema_version: str = SCHEMA_VERSION,
                 transform_version: str = TRANSFORM_VERSION) -> str:
    digest = hashlib.sha256()
    digest.update(f"schema:{schema_version}\n".encode())
    digest.update(f"transform:{transform_version}\n".encode())
    for row in sorted(rows, key=lambda r: str(r.get("match_key"))):
        digest.update(canonical_row(row).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def production_verdict(source: dict, complete: bool) -> tuple:
    """(eligible, reason). Declared permission alone never qualifies."""
    declared = (source.get("permissions") or {}).get("declared") or {}
    verified = (source.get("permissions") or {}).get("verified") or {}
    status = str(verified.get("status") or UNVERIFIED)
    if not complete:
        return False, "scan_incomplete"
    if not declared.get("production_training"):
        return False, "declared_permission_missing"
    if status != APPROVED:
        return False, f"permissions_{status.lower()}"
    if not (verified.get("by") and verified.get("at") and verified.get("scope")):
        return False, "verification_record_incomplete"
    return True, "verified_production_training"


def build_manifest(meta: dict, report, partitions: list, rows: list,
                   complete: bool, created_at: str, notes=None,
                   observations=None) -> dict:
    eligible, reason = production_verdict(meta, complete)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "transformVersion": TRANSFORM_VERSION,
        "createdAt": created_at,
        "completeness": "COMPLETE" if complete else "PARTIAL",
        "productionEligible": eligible,
        "productionEligibilityReason": reason,
        "suitableForProductionTraining": eligible,
        "source": meta,
        "counts": report.counts(),
        "rejectionReasons": report.reasons(),
        "conflicts": report.conflicts,
        "observationCounts": observations or {"accepted": 0, "rejected": 0},
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
