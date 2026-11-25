"""Command line entry point: python -m rsil ingest ..."""
import argparse
import json
import sys

from .corpus import build
from .providers import CsvMappedProvider, ProviderError, SyntheticProvider


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="rsil")
    sub = parser.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser("ingest", help="build a corpus from one provider")
    ingest.add_argument("--provider", required=True, choices=["synthetic", "csv"])
    ingest.add_argument("--out", default="data/corpus")
    ingest.add_argument("--csv", help="path to the source CSV (csv provider)")
    ingest.add_argument("--spec", help="path to the mapping spec (csv provider)")
    ingest.add_argument("--competitions", type=int, default=2)
    ingest.add_argument("--seasons", type=int, default=2)
    ingest.add_argument("--partial", action="store_true",
                        help="simulate a partial fetch (synthetic only)")
    args = parser.parse_args(argv)

    if args.provider == "synthetic":
        provider = SyntheticProvider(competitions=args.competitions,
                                     seasons=args.seasons,
                                     complete=not args.partial)
    else:
        if not (args.csv and args.spec):
            parser.error("--csv and --spec are required for the csv provider")
        provider = CsvMappedProvider(args.csv, args.spec)

    try:
        manifest = build(provider, args.out)
    except ProviderError as exc:
        print(json.dumps({"status": "FAILED", "error": str(exc)}))
        return 2
    summary = {"status": manifest["completeness"],
               "contentHash": manifest["contentHash"],
               "counts": manifest["counts"],
               "source": manifest["source"]["name"],
               "licence": manifest["source"]["licence"],
               "suitableForProductionTraining":
                   manifest["suitableForProductionTraining"],
               "manifest": f"{args.out}/manifest.json"}
    print(json.dumps(summary, indent=2))
    return 0 if manifest["completeness"] == "COMPLETE" else 3


if __name__ == "__main__":
    sys.exit(main())
