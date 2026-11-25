# Corpus contract

What `rsil` produces, what it guarantees, and what it deliberately does not.

## Canonical schema (v2)

One Parquet row per match, 31 columns, schema version `rsil-match-v2`
(`SCHEMA_VERSION`). `match_key = competition_id|season|match_id` is the
canonical identity: it is computed at ingestion, carried in every row, and used
for ordering, dedupe, conflict detection and hashing. Two sources may reuse a
`match_id`; across competitions they stay distinct rows.

Types are strict. Integer fields reject decimals (`not_an_integer:home_goals`),
floats reject NaN and infinity, and every timestamp must carry an offset
(`naive_timestamp:kickoff_utc`). Nothing is silently truncated or coerced.

## Event time versus information availability

`kickoff_utc` is **when the event happened**. `available_at` on a match row is
**when that match's outcome became known**. There is no ordering rule between
the two timestamps and none is enforced.

Finer-grained information lives in observations, each with its own
`available_at` and a `kind`:

| Kind | Group | Typical timing |
| --- | --- | --- |
| `pre_match_odds` | pre-match | before kickoff |
| `pre_match_lineup` | pre-match | before kickoff |
| `pre_match_team_news` | pre-match | before kickoff |
| `result` | post-match | after the final whistle |
| `post_match_stats` | post-match | after the match |
| `correction` | post-match | whenever a correction lands |

Unknown kinds are rejected with `unknown_kind:<kind>`.

## The pre-match invariant

`prematch_feature_inputs(match, history, observations, as_of)` is pre-match by
contract. `as_of` must not be later than the target kickoff: at kickoff it is
allowed, after kickoff it raises `TemporalError("prediction_after_kickoff")`.
The guard is `assert_prematch_timestamp`, exported so a dataset builder calls
it rather than restating it.

Inside that cutoff:

* history is admitted only when its outcome was available by `as_of` **and**
  that match kicked off before the target;
* observations are admitted only when their kind is pre-match **and** their
  `available_at` is at or before `as_of`. A `result` or `post_match_stats`
  record is refused even if its timestamp falsely claims it existed earlier;
* every refusal is counted in `excluded` (`observations`,
  `post_match_observations`, `history`), never silently dropped.

`feature_inputs` is an alias for the same function. `assert_no_leakage(rows,
as_of)` raises `leakage:<key>` if anything in a set was not available in time.

## Labels are resolved separately

`training_labels(matches, label_as_of)` answers a different question and has no
kickoff ceiling. A row is a label only when all of the following hold:

* its outcome was available by `label_as_of`;
* its status is a recognised finished status;
* `home_goals` and `away_goals` are present, integral and in `0..30`.

Unfinished fixtures, missing scores and impossible scores are dropped rather
than guessed. `training_example(..., as_of, label_as_of)` composes both: features
at the pre-match timestamp, label at the later one. Post-match data never enters
the feature path.
`prematch_feature_inputs` also returns `label_visible`, which is **timestamp-only**:
True when the source reports an outcome time at or before the cutoff. Because an
outcome timestamp before kickoff is a warning rather than a rejection, it can be
True pre-match. It is never proof that a valid label exists; `training_labels` is
the sole authority on label eligibility.

## Manifests

Every build writes `manifest.json` with:

* `contentHash` (SHA-256 over canonical rows sorted by `match_key`, salted with
  the schema and transform versions) and a `sha256` per partition file;
* `counts` (accepted, rejected, duplicates, conflicts, errors, warnings) and
  `rejectionReasons`;
* `completeness`: `COMPLETE` only when the provider reports a finished scan,
  otherwise `PARTIAL`;
* `source.permissions.declared` (what the source or spec claims) and
  `source.permissions.verified` (`status`, `by`, `at`, `evidenceUrl`, `scope`);
* `productionEligible` plus `productionBlockedReason`.

Partitions are `partitions/competition_id=<id>/season=<year>/part-00000.parquet`,
rows sorted by `match_key`, observations in
`partitions/observations/part-00000.parquet`.

## Reproducibility

Same source, same versions, same bytes: row order is deterministic, Parquet is
written with a fixed schema, and the content hash excludes build timestamps.
Changing `SCHEMA_VERSION` or `TRANSFORM_VERSION` changes the hash, which is the
point.

## Licensing behaviour

A source declares permissions in three buckets: research, production training,
redistribution. Declared is not verified. The CSV adapter always emits an
unverified source and discards any verification block in its spec, so a file we
downloaded cannot grant us rights we do not hold. `productionEligible` is a
checks-only verdict: it is **not** approval to publish, deploy or ship a model.

Current standing: football-data.co.uk is blocked for automated collection and
AI training without written permission; StatsBomb Open Data is research-only
with attribution; football-data.org and API-Football are unclarified. Only
synthetic and hand-written CC0 data is wired today. See
[`licensing-matrix.md`](licensing-matrix.md).

## Known limitations

1. Observation payloads are free-form JSON, not typed per kind, so a
   `pre_match_lineup` payload is not validated against a lineup schema.
2. Duplicate detection keeps the first record and loses the duplicate's source
   provenance; the losing source and its record id are not preserved.
3. Licensing evidence is a URL string. Long-term it must record the actual
   evidence reference and the scope it covers, not just a link.
4. `productionEligible: true` means the checks passed. It is never approval to
   publish or deploy a model.
