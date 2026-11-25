# Corpus contract

## Canonical schema (`rsil-match-v1`)

One row per match, 30 fields: competition, season, teams, kickoff, status, goals
(full time and half time), shots and shots on target, xG, three-way odds with their
capture time, provenance (`source_name`, `source_record_id`, `source_url`,
`ingested_at`), an `is_synthetic` flag, and **both** time fields:

- `kickoff_utc` is when the event happened.
- `available_at` is when the information could be known.

A row whose `available_at` precedes its `kickoff_utc` is rejected as a leakage error,
never accepted with a warning.

## Adapter contract

A provider is any object exposing:

```python
meta: SourceMeta            # name, licence, licenceUrl, attribution, sourceUrl,
                            # retrievedAt, permitted{research, production_training,
                            # redistribution}
fetch() -> ProviderResult   # records: list[dict], complete: bool, meta, notes
```

Adding a source means writing one adapter, or one JSON mapping spec for tabular
sources (`rsil.providers.CsvMappedProvider`), and changing no corpus code. A source
that cannot be read raises `ProviderError`; it never becomes an empty corpus.

## Validation

Rejected with a machine-readable reason: missing required fields, unparseable
timestamps, information available before kickoff, self-matches, impossible scores,
a score on an unfinished match, invalid xG and invalid odds. Identical duplicates are
counted once. A conflicting result keeps the first observation and records the conflict
in the manifest.

## Reproducibility

`contentHash` is SHA-256 over the canonical JSON of every accepted row, sorted by
`match_id`. Parquet is written with a fixed Arrow schema, sorted rows and no
time-varying metadata, so two runs over unchanged source data produce identical
`contentHash` values and byte-identical partition files. That is asserted in the tests.

## Manifest

`schemaVersion`, `transformVersion`, `createdAt`, `completeness`
(`COMPLETE`/`PARTIAL`), `suitableForProductionTraining` (always false for now),
`source` (licence metadata), `counts`, `rejectionReasons`, `conflicts`,
`partitions` (path, rows, sha256), `contentHash`, `notes`.
