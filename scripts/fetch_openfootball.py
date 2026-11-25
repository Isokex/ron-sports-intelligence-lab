"""Fetch pinned OpenFootball source files into the ignored data directory.

Never touches tracked content: sources land in ``data/openfootball/<commit>/``.
Hashes are verified against ``config/openfootball-sources.json`` after download,
so a changed upstream file fails loudly instead of entering a build.

Usage:
    python scripts/fetch_openfootball.py [--config config/openfootball-sources.json]
"""
import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRACKED = ("src", "tests", "docs", "config", "scripts", ".github")


def _guard(path: str) -> str:
    resolved = os.path.realpath(path)
    root = os.path.realpath(REPO_ROOT)
    if not resolved.startswith(os.path.join(root, "data") + os.sep):
        raise SystemExit(f"refusing to write outside data/: {resolved}")
    for tracked in TRACKED:
        if resolved == os.path.join(root, tracked) or resolved.startswith(
                os.path.join(root, tracked) + os.sep):
            raise SystemExit(f"refusing to write into tracked content: {resolved}")
    return resolved


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=os.path.join("config", "openfootball-sources.json"))
    args = parser.parse_args(argv)

    with open(os.path.join(REPO_ROOT, args.config), encoding="utf-8") as fh:
        config = json.load(fh)
    commit = config["commit"]
    root = _guard(os.path.join(REPO_ROOT, "data", "openfootball", commit))
    os.makedirs(root, exist_ok=True)
    retrieved_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    evidence = {"commit": commit, "retrieved_at": retrieved_at, "files": []}

    for item in config["seasons"]:
        url = (f"https://raw.githubusercontent.com/{config['repository']}/{commit}/"
               f"{item['path']}")
        target = _guard(os.path.join(root, item["path"]))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                raw = response.read()
        except urllib.error.URLError as exc:
            raise SystemExit(f"download failed for {url}: {exc}")
        digest = hashlib.sha256(raw).hexdigest()
        if digest != item["sha256"]:
            raise SystemExit(
                f"hash mismatch for {item['path']}: config says {item['sha256']}, "
                f"source returned {digest}. Upstream changed; do not build.")
        with open(target, "wb") as fh:
            fh.write(raw)
        evidence["files"].append({"path": item["path"], "url": url,
                                  "sha256": digest, "bytes": len(raw)})
        print(f"ok {item['season']} {len(raw)} bytes {digest[:12]}")

    with open(os.path.join(root, "retrieval.json"), "w", encoding="utf-8") as fh:
        json.dump(evidence, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"source root: {root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
