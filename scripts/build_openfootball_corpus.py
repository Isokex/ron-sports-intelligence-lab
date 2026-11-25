"""Build the OpenFootball corpus and its audit.

Runs the pinned adapter through the Phase 1 pipeline (validate -> partitioned
Parquet -> manifest), then writes the provenance sidecar and the quality audit.
Everything lands under the ignored ``data/`` tree; nothing tracked is written.

Usage:
    python scripts/build_openfootball_corpus.py \
        --out data/corpus/openfootball-epl-v1
"""
import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "src"))

import pyarrow.parquet as pq  # noqa: E402

from rsil import corpus  # noqa: E402
from rsil.providers.openfootball import (DEFAULT_ALIASES, DEFAULT_CONFIG,  # noqa: E402
                                        DERIVATION_RULE, OpenFootballAdapter)

TRACKED = ("src", "tests", "docs", "config", "scripts", ".github")


def _guard(path: str) -> str:
    resolved = os.path.realpath(path)
    root = os.path.realpath(REPO_ROOT)
    data_root = os.path.join(root, "data")
    if not resolved.startswith(data_root + os.sep):
        raise SystemExit(f"refusing to build outside data/: {resolved}")
    for tracked in TRACKED:
        if resolved == os.path.join(root, tracked) or resolved.startswith(
                os.path.join(root, tracked) + os.sep):
            raise SystemExit(f"refusing to build into tracked content: {resolved}")
    return resolved


def _partition_rows(out_dir: str):
    rows = []
    for dirpath, _dirnames, filenames in os.walk(os.path.join(out_dir, "partitions")):
        for name in sorted(filenames):
            if not name.endswith(".parquet") or "observations" in dirpath:
                continue
            table = pq.read_table(os.path.join(dirpath, name))
            rows.extend(table.to_pylist())
    return rows


def _acquisition_evidence(adapter) -> dict:
    """Actual retrieval evidence, kept distinct from the configured timestamp.

    The build timestamp is pinned in config so output is deterministic; that
    makes it a *configured* value, not proof of when bytes were fetched. The
    fetch step writes ``retrieval.json`` next to the sources, and the audit
    reports it as acquisition evidence with an explicit consistency check. When
    the file is absent the audit says ``unrecorded`` rather than presenting the
    configured timestamp as if it were observed.
    """
    path = os.path.join(adapter.source_root, "retrieval.json")
    if not os.path.isfile(path):
        return {"status": "unrecorded",
                "path": None,
                "reason": "retrieval.json not found; the configured timestamp is "
                          "not acquisition evidence"}
    try:
        with open(path, encoding="utf-8") as fh:
            evidence = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "unreadable", "path": path, "reason": str(exc)}
    recorded = {item.get("path"): item.get("sha256")
                for item in evidence.get("files") or [] if isinstance(item, dict)}
    expected = {item.path: item.sha256 for item in adapter.files}
    consistent = recorded == expected
    return {"status": "recorded",
            "path": os.path.relpath(path, REPO_ROOT),
            "retrievedAt": evidence.get("retrieved_at"),
            "commit": evidence.get("commit"),
            "commitMatchesConfig": evidence.get("commit") == adapter.config["commit"],
            "consistent": consistent,
            "mismatchedFiles": sorted(set(recorded) ^ set(expected)) or
                               sorted(k for k in expected
                                      if recorded.get(k) != expected[k])}


def _audit(adapter, manifest: dict, out_dir: str, built_at: str) -> dict:
    rows = _partition_rows(out_dir)
    by_season = defaultdict(lambda: {"accepted": 0, "finished": 0,
                                     "missing_scores": 0, "dates": []})
    for row in rows:
        bucket = by_season[row["season"]]
        bucket["accepted"] += 1
        if row.get("home_goals") is not None and row.get("away_goals") is not None:
            bucket["finished"] += 1
        else:
            bucket["missing_scores"] += 1
        bucket["dates"].append(row["kickoff_utc"][:10])

    source_counts = {item.season: item.records for item in adapter.files}
    rejected = Counter(entry["reason"] for entry in adapter.rejections)
    rejected_by_season = Counter()
    unresolved = defaultdict(lambda: {"count": 0, "seasons": set()})
    for entry in adapter.rejections:
        rejected_by_season[entry["season"]] += 1
        if entry["reason"].startswith("unknown_team:"):
            name = entry["reason"].split(":", 1)[1]
            unresolved[name]["count"] += 1
            unresolved[name]["seasons"].add(entry["season"])

    provenance_names = []
    for item in adapter.provenance:
        provenance_names.extend([item["source_team_home"], item["source_team_away"]])
    coverage = adapter.resolver.coverage(provenance_names)

    seasons = []
    for season, count in sorted(source_counts.items()):
        bucket = by_season.get(season, {"accepted": 0, "finished": 0,
                                        "missing_scores": 0, "dates": []})
        seasons.append({
            "season": season,
            "sourceRecords": count,
            "acceptedRecords": bucket["accepted"],
            "rejectedRecords": rejected_by_season.get(season, 0),
            "finishedMatches": bucket["finished"],
            "missingScores": bucket["missing_scores"],
            "dateCoverage": {"first": min(bucket["dates"]),
                             "last": max(bucket["dates"])} if bucket["dates"] else None,
        })

    return {
        "dataset": {
            "outDir": os.path.relpath(out_dir, REPO_ROOT),
            "contentHash": manifest["contentHash"],
            "schemaVersion": manifest["schemaVersion"],
            "transformVersion": manifest["transformVersion"],
            "createdAt": manifest["createdAt"],
            "productionEligible": manifest["productionEligible"],
            "productionEligibilityReason": manifest["productionEligibilityReason"],
            "completeness": manifest["completeness"],
        },
        "source": {
            "provider": "openfootball",
            "repository": adapter.config["repository"],
            "commit": adapter.config["commit"],
            "configuredRetrievedAt": adapter.config["retrieved_at"],
            "configuredRetrievedAtNote": "pinned in config for deterministic output; "
                                         "not evidence of when bytes were fetched",
            "acquisition": _acquisition_evidence(adapter),
            "licence": adapter.config["licence"],
            "files": [{"season": item.season, "path": item.path,
                       "sha256": item.sha256, "bytes": item.bytes,
                       "sourceRecords": item.records}
                      for item in adapter.files],
        },
        "temporal": {"derivationRule": DERIVATION_RULE,
                     "availabilityLagMinutes": 120,
                     "advisoryKickoffTimes": True},
        "counts": {
            "sourceRecords": sum(source_counts.values()),
            "acceptedRecords": len(rows),
            "rejectedRecords": len(adapter.rejections),
            "duplicates": manifest["counts"].get("duplicates", 0),
            "conflicts": len(manifest["conflicts"]),
        },
        "seasons": seasons,
        "rejections": {"byReason": dict(sorted(rejected.items())),
                       "detail": adapter.rejections[:200]},
        "scoreFormats": dict(sorted(adapter.score_formats.items())),
        "availabilityDerivation": dict(Counter(
            item["derivation_rule"] for item in adapter.provenance)),
        "teamMapping": {"version": adapter.resolver.version,
                        "teams": len({row["home_team_id"] for row in rows} |
                                     {row["away_team_id"] for row in rows}),
                        "coverage": coverage,
                        "unresolved": [{"name": name, "count": value["count"],
                                        "seasons": sorted(value["seasons"])}
                                       for name, value in sorted(unresolved.items())]},
        "validation": {"rejectionReasons": manifest["rejectionReasons"],
                       "partitions": len(manifest["partitions"]),
                       "notes": manifest["notes"]},
        "builtAt": built_at,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--aliases", default=DEFAULT_ALIASES)
    parser.add_argument("--source-root", default=None)
    parser.add_argument("--out", default=os.path.join("data", "corpus",
                                                      "openfootball-epl-v1"))
    args = parser.parse_args(argv)

    config = json.load(open(os.path.join(REPO_ROOT, args.config), encoding="utf-8"))
    commit = config["commit"]
    source_root = args.source_root or os.path.join("data", "openfootball", commit)
    out_dir = _guard(os.path.join(REPO_ROOT, args.out))

    adapter = OpenFootballAdapter(
        source_root=os.path.join(REPO_ROOT, source_root),
        config_path=os.path.join(REPO_ROOT, args.config),
        aliases_path=os.path.join(REPO_ROOT, args.aliases),
    )
    built_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    # Deterministic createdAt: the dataset must not depend on when it was built.
    created_at = config["retrieved_at"]
    manifest = corpus.build(adapter, out_dir, created_at=created_at)

    provenance_dir = os.path.join(out_dir, "provenance")
    os.makedirs(provenance_dir, exist_ok=True)
    provenance_path = os.path.join(provenance_dir, "records.jsonl")
    with open(provenance_path, "w", encoding="utf-8") as fh:
        for item in sorted(adapter.provenance, key=lambda p: p["match_key"]):
            fh.write(json.dumps(item, sort_keys=True) + "\n")

    audit = _audit(adapter, manifest, out_dir, built_at)
    audit["provenanceSidecar"] = os.path.relpath(provenance_path, out_dir)
    audit_path = os.path.join(out_dir, "audit.json")
    with open(audit_path, "w", encoding="utf-8") as fh:
        json.dump(audit, fh, indent=2, sort_keys=True)
        fh.write("\n")

    print(json.dumps({"outDir": os.path.relpath(out_dir, REPO_ROOT),
                      "contentHash": manifest["contentHash"],
                      "counts": audit["counts"],
                      "seasons": len(audit["seasons"]),
                      "scoreFormats": audit["scoreFormats"],
                      "teamMappingCoverage": audit["teamMapping"]["coverage"]
                      ["recordsCoverage"]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
