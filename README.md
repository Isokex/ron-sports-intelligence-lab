# RON Sports Intelligence Lab

Provider-neutral historical football corpus and, later, the training and evaluation
platform that supplies validated models to Ron Weasley the II.

**Status:** Phase 1 foundation. Corpus ingestion, validation, partitioned Parquet and
content-hashed manifests. No model training yet, and nothing here is production-ready.

## Quick start

```bash
pip install -e ".[dev]"
python -m rsil ingest --provider synthetic --out data/corpus
python -m rsil ingest --provider csv --csv fixtures/demo_matches.csv \
    --spec fixtures/demo_spec.json --out data/demo
python -m pytest -q
```

## What it does

- One canonical match schema, with event time and information-availability kept apart.
- Provider adapters: `synthetic` (generated, CC0) and `csv` (any permitted tabular
  source via a JSON mapping spec). Adding a source touches no corpus code.
- Validation, duplicate detection and conflict recording, each with a machine-readable
  reason; a failed read raises instead of returning an empty corpus.
- Partitioned Parquet (`competition_id=.../season=...`) and a manifest carrying source
  licence metadata, permitted-use flags, counts, partition hashes and a `contentHash`
  that is identical across reruns over unchanged data.

## Licensing

**No third-party data is included, and no unlicensed source is automated.** Football-Data.co.uk
is explicitly not used: its policy excludes commercial and AI data-training projects that
involve automated collection. See [docs/licensing-matrix.md](docs/licensing-matrix.md) before
adding any provider. Every manifest states `suitableForProductionTraining: false` until a
source is cleared in writing.

## Layout

```
src/rsil/{schema,quality,corpus,manifest,cli}.py
src/rsil/providers/{base,synthetic,csv_mapped}.py
docs/{corpus,licensing-matrix}.md
fixtures/            # hand-written demonstration data, CC0
tests/               # hermetic; no network
```
