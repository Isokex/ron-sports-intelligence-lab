# Phase 2B corpus build: OpenFootball English Premier League

Research corpus of historical fixtures and reported final scores for the English
Premier League, seasons 2019-20 to 2024-25, built from OpenFootball CC0 data at a
pinned commit. **Research only:** the manifest reports
`productionEligible: false`, and nothing here is approval to publish or deploy.

## Source

| Item | Value |
|---|---|
| Provider | OpenFootball |
| Repository | `openfootball/football.json` |
| Commit | `e6744429ee395bc86f247348c6184bb08d4eb361` (committed 2026-09-22) |
| Files | `{season}/en.1.json` for six seasons |
| Licence | CC0 1.0 Universal, `LICENSE.md` at the pinned commit |
| Attribution | OpenFootball (openfootball/football.json), public domain under CC0 1.0 |
| Configured retrieval timestamp | 2026-11-25T14:27:47Z, pinned in `config/openfootball-sources.json` for deterministic output. This is **not** acquisition evidence. |

### Acquisition evidence

The timestamp above is a *configured* value, chosen so repeated builds produce
identical output. When bytes were actually fetched is a separate fact, recorded
by `scripts/fetch_openfootball.py` in `retrieval.json` beside the sources at
`data/openfootball/<commit>/retrieval.json`.

For the build described here that file records:

| Evidence | Value |
|---|---|
| Observed retrieval time | 2026-11-25T14:36:01Z, later than the configured 14:27:47Z because fetching and building are separate steps |
| Commit observed | `e6744429ee395bc86f247348c6184bb08d4eb361`, matching the pinned config |
| Hash consistency | every downloaded file's SHA-256 matches the pinned value, no mismatches |
| Recorded at | `data/openfootball/<commit>/retrieval.json` (ignored, never tracked) |

`audit.json` reports this under `source.acquisition` with `status`, the observed
`retrievedAt`, `commitMatchesConfig`, `consistent` and `mismatchedFiles`, and it
reports `source.configuredRetrievedAt` separately with the caveat that the
configured value is not evidence. If `retrieval.json` is absent the audit says
`status: "unrecorded"` and makes no retrieval claim at all; it never substitutes
the configured timestamp for observed evidence. The same holds for the value in
this document: it describes the recorded build, not a promise about any other
run.

Per-file SHA-256 hashes are recorded in `config/openfootball-sources.json` and
re-verified on every read, so a changed upstream file fails the build instead of
entering a corpus silently. Raw sources live in `data/openfootball/<commit>/`
and are never tracked.

## Reproduce

```bash
python scripts/fetch_openfootball.py                     # download + verify hashes
python scripts/build_openfootball_corpus.py \
    --out data/corpus/openfootball-epl-v1               # build + audit
python -m pytest                                        # full suite
```

Both scripts refuse to write outside `data/` and refuse any tracked directory.
`created_at` is the pinned retrieval timestamp rather than the build clock, so
two builds produce the same manifest hash and byte-identical partitions.

## What the build produces

* `partitions/competition_id=eng-premier-league/season=<season>/part-00000.parquet`
* `manifest.json`: content hash, counts, licence block, permissions, partitions
* `provenance/records.jsonl`: one line per accepted match with the raw source
  teams, raw score object, source index, file hash and temporal derivation
* `audit.json`: the quality audit below

## Audit results

| Season | Source | Accepted | Rejected | Finished | Date coverage |
|---|---|---|---|---|---|
| 2019-20 | 380 | 314 | 66 | 314 | 2019-08-09 to 2020-06-30 |
| 2020-21 | 380 | 380 | 0 | 380 | 2020-09-12 to 2021-05-23 |
| 2021-22 | 380 | 380 | 0 | 380 | 2021-08-13 to 2022-05-22 |
| 2022-23 | 380 | 380 | 0 | 380 | 2022-08-05 to 2023-05-28 |
| 2023-24 | 380 | 380 | 0 | 380 | 2023-08-11 to 2024-05-19 |
| 2024-25 | 380 | 380 | 0 | 380 | 2024-08-16 to 2025-05-25 |

Totals: 2,280 source records, 2,214 accepted, 66 rejected, 0 duplicates,
0 conflicts, 0 missing scores, 0 invalid scores. Team mapping `team-aliases-v1`
covers 100% of accepted records across 27 clubs and 39 distinct source names.

Score-format distribution: `object:ft,ht` 2,093, `object:ft` 121. Bare arrays do
not occur in these six files but are supported and tested, because they occur in
other OpenFootball seasons.

### Known gap: 66 records in 2019-20

OpenFootball dates 66 matches of 2019-20 in July 2019, before the season's own
opening matchday. The fixtures are the real 2020-07-01 restart matches: for
example `AFC Bournemouth v Newcastle United 1-4` and `Arsenal FC v Norwich City
4-0` are 1 July 2020 results carrying the year 2019. Accepting them would make
June 2020 results look available in July 2019, which is a leakage hazard, so the
adapter rejects any record dated before the season's earliest `Matchday 1`
record and reports the reason `date_before_season_opener`.

Consequence, stated plainly: **2019-20 holds 314 of 380 matches.** The 66
rejected fixtures are not repaired, re-dated or imputed. Any model trained on
this corpus must treat 2019-20 as partial, and the audit records the gap.

## Temporal contract

Every record is date-only, so `derived_available_at` is the end of the recorded
UTC date plus 120 minutes: a match on 2019-08-09 becomes available at
2019-08-10T02:00:00Z. `kickoff_utc` carries the start of the recorded UTC date,
the earliest plausible kickoff and therefore the conservative pre-match cutoff.
Source `time` values are advisory only, recorded in the provenance sidecar and
never converted to an instant, because the source states no timezone. Same-day
results are therefore invisible to any pre-match cutoff on that date, which
`tests/test_openfootball_adapter.py` asserts directly.

## Team identity

`config/team-aliases-v1.json` maps 39 observed source names to 27 canonical club
ids. Resolution is exact alias lookup: no fuzzy matching, no case-insensitive
fallback, no automatic merging. The file is generated with a documented
normalisation rule (strip `FC`/`AFC`/`CF`/`SC`/`AC`, expand `&`) used **only** to
propose groupings for human review; the aliases themselves are explicit. An
unresolved name rejects the record with `unknown_team:<name>` and appears in the
audit with counts and seasons.

## Boundaries observed

No odds, lineups, injuries, event data or xG. No other provider, no paid service,
no model training, no Ron integration, no deployment, no GitHub Release. Datasets
stay in the ignored `data/` tree; only configuration, code, tests and this
document are tracked.
