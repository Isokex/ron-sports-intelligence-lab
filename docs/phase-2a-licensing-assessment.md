# Phase 2A — Historical Data Licensing and Acquisition Assessment

**Repository:** `Isokex/ron-sports-intelligence-lab`
**Branch:** `docs/phase-2a-licensing-assessment`
**Base commit:** `ae052324c65fc9b3def9732f77c579bd9683c15f` (Phase 1 close)
**Date of assessment:** 25 November 2026
**Status:** documentation only. No accounts created, no datasets acquired, no vendor contacted, nothing purchased.

---

## 1. Executive summary

**No commercial API provider reviewed here has supplied an affirmative, bespoke agreement permitting model training.** That is the single most important finding, and it survives every technical comparison in this document: several providers would give us excellent data, and none of them has said in writing that we may train on it. OpenFootball is different in kind rather than an exception: its CC0 dedication is a public-domain basis for the intended data use, not a vendor's grant. Section 5 keeps those two bases distinct, and section 10 separates legal permission from internal production approval.

The evidence splits into three groups.

**Explicit prohibitions.** Football-Data.co.uk states its data is not intended for commercial or AI data-training projects and restricts automated collection. Sports Reference (FBref, Stathead) prohibits use of its data for training, fine-tuning, prompting or instructing AI models, and withdrew advanced xG data in January 2026. SofaScore's terms prohibit scraping, aggregating or reproducing site content without express consent. These are closed.

**Silence, which is not permission.** football-data.org, API-Football and TheStatsAPI grant API access and say nothing about model training. Their terms describe what an application may do with responses; none of them licenses the creation of a training corpus, and API-Football and TheStatsAPI both prohibit caching or resale in ways that cut against building one.

**Conditional.** Sportmonks' general terms forbid storage and restrict use to personal, non-commercial purposes, while its Enterprise page advertises commercial use, storage and historical seasons. The reconciliation is a contract, not a page: training rights must appear in a written Enterprise agreement. Sportradar and StatsBomb commercial are enterprise contracts with no published terms, and Sportradar requires certified destruction of historical data on exit, which puts trained-model retention in question.

**One provider is legally clear.** OpenFootball is dedicated to the public domain under CC0, so fixtures and results may be stored, trained on, used commercially and kept indefinitely without anyone's permission, and that waiver is irrevocable. It carries no odds, no event data, no lineups and no xG. Note what this does not do: CC0 settles the licence question and nothing else. Internal production approval, evidence records and publication authorisation are ours to grant and have not been granted (section 10).

**Recommendation: GO for a research corpus built on OpenFootball, and NO-GO for training on every other provider until written answers arrive.** The corpus is research-only and carries `productionEligible: false`: CC0 permits more, but our evidence and approval gates do not yet support more. OpenFootball supports Elo, Dixon-Coles, independent Poisson and basic form features, which is enough to prove the training pipeline end to end on a clean legal footing. It cannot support goals-quality, lineup, injury or market models. Phase 2B should build the OpenFootball corpus, not wait for vendor replies, and the licensing questions in section 8 should be sent in parallel.

---

## 2. Research methodology and sources

Rules applied throughout:

* **Silence is UNKNOWN, never PERMITTED.** A provider that does not mention model training has not licensed it.
* **Access is not a licence.** An API key, a paid plan or a cache header establishes none of the rights in section 5.
* **Marketing is not contract.** Claims on a pricing or comparison page are labelled as marketing unless the same statement appears in binding terms.
* **One right, one verdict.** Storage, training, commercial deployment and redistribution are assessed separately, because providers routinely grant one and withhold another.
* **UNKNOWN is recorded as UNKNOWN.** Where a page was unreachable or JavaScript-rendered, the document says so rather than guessing.

Sources were read on **25 November 2026** and are cited with their URL at each profile. Primary evidence means the provider's own terms, licence or documentation. Secondary evidence means an aggregator, a competitor comparison page, a press article or an indexed search excerpt; it is always marked as such and never used on its own to grant a right.

Access notes worth recording, because they are themselves evidence about automated use:

* `api-football.com/documentation-v3` returns **403 Forbidden** to a non-browser client, and `api-football.com/terms` likewise. Documentation is reachable only through a browser or an indexed copy.
* `sofascore.com` terms are JavaScript-rendered; the body could not be retrieved directly, and the Internet Archive copy returns 404. The prohibition quoted in section 4.9 comes from the page's indexed text and is labelled accordingly.
* `sportradar.com` and Stats Perform publish no public pricing or terms for data licensing; both route to sales contact.

---

## 3. Provider comparison matrix

Scores are 0–5. Licensing certainty is weighted as a gate, not a summand: a provider that fails licensing cannot be rescued by a high technical score. "Rights verdict" is the worst-case status across the nine rights in section 5 for our intended use (research corpus, then production training). It records **legal permission under the source licence only**. It is not internal production approval: even a PERMITTED row needs a verified evidence record, a named human approver and a separate publication authorisation (section 10).

| Provider | Licensing certainty | Historical depth | Competition coverage | Statistical richness | Odds coverage | Timestamp quality | Completeness / reliability | Cost & value | Integration effort | Rights verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| OpenFootball (CC0) | **5** | 3 | 2 | 1 | 0 | 2 | 3 | 5 | 5 | **PERMITTED** |
| football-data.co.uk | 1 (explicitly excluded) | 5 | 3 | 3 | 4 | 3 | 4 | 5 | 3 | **PROHIBITED** |
| StatsBomb Open Data | 3 (research only) | 2 | 2 | **5** | 0 | 4 | 4 | 5 | 3 | **CONDITIONAL** |
| StatsBomb commercial | 2 (contract only) | 5 | 4 | 5 | 1 | 5 | 5 | 1 | 2 | **CONDITIONAL** |
| API-Football | 2 | 4 | 4 | 3 | 2 | 3 | 3 | 4 | 4 | **UNKNOWN** |
| Sportmonks | 3 | 4 | **5** | 4 | 4 | 4 | 4 | 3 | 3 | **CONDITIONAL** |
| football-data.org | 2 | 3 | 3 | 2 | 1 | 3 | 3 | 4 | 5 | **UNKNOWN** |
| TheStatsAPI | 2 | 4 | 4 | 4 | 4 | 3 | 3 | 3 | 3 | **UNKNOWN** |
| Sportradar | 2 (contract only) | 5 | 5 | 5 | 4 | 5 | 5 | 1 | 2 | **CONDITIONAL** |
| Sports Reference (FBref / Stathead) | 1 (explicitly excluded) | 4 | 4 | 4 | 1 | 3 | 4 | 3 | 2 | **PROHIBITED** |
| SofaScore | 1 | 4 | 5 | 4 | 3 | 3 | 3 | 5 | 1 | **PROHIBITED** |

Reading the matrix: the two highest technical scores (Sportradar, StatsBomb commercial) sit at the bottom on cost, and the two cheapest rich sources (football-data.co.uk, Sports Reference) are the two that explicitly refuse AI training. OpenFootball is the only row where the licensing column is a 5, and its richness column is a 1. That trade is the whole of Phase 2A.
---

## 4. Individual provider assessments

### 4.1 Football-Data.co.uk — PROHIBITED for our use

**Sources.** `https://www.football-data.co.uk/` (home), `https://www.football-data.co.uk/notes.txt` (data dictionary), `https://www.football-data.co.uk/disclaimer.php` (disclaimer page, marked "Updated: 24/11/26"), read 25 Nov 2026.

**What it is.** Free CSV files covering up to 22 European divisions, 25 seasons back to 1993/94, with match statistics from 2000/01 and historical bookmaker odds including closing prices. The data dictionary confirms the fields (`FTHG`, `FTAG`, `HS`, `HST`, `HxG`, `B365H`, `PSCH`, `PSCD`, `PSCA` and so on) and states that odds are collected on Friday afternoons, which tells us the snapshots are manually assembled rather than machine-timestamped.

**The restriction.** The site's published policy excludes commercial and AI data-training projects that use bots or scrapers, and restricts automated download to roughly twice weekly. `robots.txt` blocks AI crawlers. The disclaimer page itself is a liability disclaimer and says nothing about training rights, so the operative restriction is the stated policy, not a licence.

**Why this matters beyond the words.** The site is one person's manually curated compilation of odds that originate with bookmakers. Even with permission from the site, the underlying bookmaker prices may carry their own terms, and the site does not purport to be an official rights holder. Permission from the compiler would not settle the third-party question.

**Verdict.** PROHIBITED for AI training and for automated acquisition. Do not build an adapter. Keep the existing block in `docs/licensing-matrix.md`. Written permission, if ever obtained, would still not resolve the bookmaker-rights question.

### 4.2 OpenFootball — PERMITTED (CC0) for the intended data use, not automatically production-approved

**Sources.** `https://github.com/openfootball` and per-competition repositories, read 25 Nov 2026. Project materials dedicate the data to the public domain under CC0 1.0.

**What it is.** Plain-text and JSON fixtures and results, maintained by volunteers, covering major leagues and international tournaments with long historical runs for the biggest competitions. No odds, no event data, no lineups, no injuries, no xG.

**Rights.** CC0 waives copyright and related rights to the extent the dedicator holds them. Research, storage, automated acquisition, ML training, derived features, commercial use, redistribution and indefinite retention are all PERMITTED, and the waiver is irrevocable, so trained-model retention after any cancellation is not a question that arises.

**The honest caveat.** CC0 covers the *compilation*. It does not grant rights in competition names, club crests, fixture lists as organised by a league, or any third-party marks, and it does not warrant that a volunteer did not transcribe a source they had no right to copy. For a research corpus of scores and dates that is acceptable; for a public commercial product carrying league branding it is not, and the branding question is ours to avoid rather than the data's to answer.

**Coverage limits.** Fixtures and results only. No odds, no event data, no player-level data, and no timestamp for when a result became known. The temporal rule that governs that last gap is specified below.

### 4.2.1 Temporal availability rule for OpenFootball (implementation requirement for Phase 2B)

OpenFootball records a match date, not a publication time, so a result cannot be treated as available at kickoff, at the start of the day, or at any moment before the match could have finished. Deriving `available_at` from the match date alone is not conservative enough. The rule for Phase 2B:

1. **Never timestamp a result before full time.** Derived availability is `kickoff_utc + 120 minutes` at the earliest, with kickoff taken as midday UTC when the source supplies a date only, so the bound is conservative in both directions. If a source later supplies a real kickoff time, the bound uses it.
2. **Do not use same-day results as pre-match features.** Any historical result whose derived availability falls after the prediction timestamp is excluded and counted, even when its fixture date equals the target date.
3. **Record the derivation, not only the value.** Each row carries `source_timestamp` (what the file said, date only), `derived_available_at`, `derivation_rule` (a versioned id such as `openfootball-date-only-v1`) and `uncertainty` (the window between earliest and latest plausible publication). A dataset missing those four fields is not eligible for training.
4. **Prove the boundary with leakage tests before training.** Required cases: a same-day result is excluded at a pre-match `as_of`; a derived availability is never earlier than full time; advancing `as_of` admits a result exactly once; and two builds from identical inputs produce identical exclusions.

This is a recorded requirement for Phase 2B. No Phase 1 code, schema or ingestion path changes in this correction.

### 4.3 StatsBomb — research sandbox (CONDITIONAL), commercial contract only

**Sources.** `https://github.com/statsbomb/open-data` and the Hudl/StatsBomb open-data page, read 25 Nov 2026; commercial terms are not published and route to sales.

**Open Data.** Event-level data with xG for a curated set of competitions, free for research use with attribution. The user agreement restricts commercial exploitation and the use of the data to build a competing product, and is silent on model training. Silence is UNKNOWN, and the agreement has not been reviewed by us in full, so Open Data stays isolated: research sandbox only, never merged into a production corpus, never redistributed, and not used to publish derived commercial analysis.

**Commercial.** Full event data, broad competition coverage, negotiated contract, no published price. Any training right would come from that contract, not from the open licence, so the verdict is CONDITIONAL pending a written agreement that names model training, derived-model retention and post-termination use.

**Verdict.** Useful for xG research in an isolated sandbox. Not usable as a production corpus on current evidence.

### 4.4 API-Football — UNKNOWN, with resale restrictions

**Sources.** `https://www.api-football.com/documentation-v3` (403 to non-browser clients; read via indexed copy), `https://www.api-football.com/terms` (403), the beginner guide at `https://www.api-football.com/news/post/how-to-get-started-with-api-football-the-complete-beginners-guide`, and the API-Sports documentation mirror `https://api-sports.io/documentation/football/v3`, all read 25 Nov 2026.

**Coverage.** Seasons endpoint returns available years; the documented list begins at 2008 and runs to 2026, with real depth from 2010 onward and thin coverage before that. Fixtures, results, team and player statistics, lineups, events, injuries and pre-match odds are all present for major leagues. Rate limiting is expressed as a **daily** quota through `x-ratelimit-requests-remaining`, sized by plan, with the free tier at 100 requests/day; a per-minute ceiling is documented inconsistently across pages and is recorded here as UNKNOWN.

**Rights.** The terms grant no data licence, prohibit resale of the API or its data, and say nothing about training, retention or derived models. Access is intended for automated clients, which establishes automation, not training rights.

**Verdict.** UNKNOWN for every right that matters. Not production-approved. Written clarification required.

### 4.5 Sportmonks — CONDITIONAL, contract-dependent, with a documented internal contradiction

**Sources.** `https://www.sportmonks.com/terms-of-service/` (General Terms and Conditions of Sportmonks B.V.), `https://www.sportmonks.com/football-api/enterprise-plan/`, `https://www.sportmonks.com/faq/`, `https://docs.sportmonks.com/v3/`, read 25 Nov 2026.

**Documentation and limits.** API 3.0 documentation is at `docs.sportmonks.com/v3`, with a rate-limit page in the navigation; the specific limits page returned 404 on the URLs tried, and a secondary aggregator (`apis.io/providers/sportmonks`) reports plan limits expressed as **3,000 API calls per entity per hour** on a €249/month tier. That figure is secondary evidence and must be confirmed against the docs or a contract. The FAQ states historical data is available "from roughly 2010 onwards depending on availability" and that paid plans include a 14-day trial.

**The contradiction, quoted.** General terms, Article 6.2: "Reproduction, transfer, distribution, or storage of Sportmonks' services or data is prohibited without prior written consent from Sportmonks." Article 6.3: "Use of data and/or other materials from Sportmonks is permitted only for personal and non-commercial purposes." Article 5.4 prohibits resale without consent; Article 5.6 limits use to a single domain absent written consent.

The Enterprise page says the opposite in plain words: "Store, transfer and distribute the data inside your own product, including caching it in your own database" and "Make money from what you build. Commercial use is the point", with historical seasons "covered by the same permitted use as live data".

**Neither document mentions model training.** Even the Enterprise page, which is unusually explicit about storage and commercial use, describes building products on the data, not training models from it. So storage and commercial use become PERMITTED under an Enterprise contract, while training remains UNKNOWN until the agreement says otherwise.

**Provenance.** Sportmonks states plainly: "We are your data provider, not an official rights holder for the competitions covered". That is a useful honesty and a real limit: regulated competitions may require separately licensed data.

**Verdict.** CONDITIONAL. The only viable path is a written Enterprise agreement that names model training, derived-model retention and post-termination use. Do not treat the marketing page as that agreement.

### 4.6 football-data.org — UNKNOWN, cheap cross-check only

**Sources.** `https://www.football-data.org/`, its terms and pricing pages, read 25 Nov 2026.

**What it is.** A clean REST API for fixtures, results, tables and squads across major competitions, with a free tier (registered, rate-limited to 10 requests/minute) and paid tiers for higher limits and commercial use. Historical depth is shallower than the CSV compilers.

**Rights.** The terms permit use of the API within plan limits, allow commercial use on paid plans, and are silent on model training, corpus retention and derived models. Its own description of what a plan permits is about serving an application, not about creating a training set.

**Verdict.** UNKNOWN for training. Usable as a low-cost cross-check for fixtures and results if a written answer confirms it; not a corpus.

### 4.7 TheStatsAPI — UNKNOWN, and its relationship to Football-Data.co.uk is promotion, not provenance

**Sources.** `https://www.thestatsapi.com/`, `https://football-data.co.uk/thestatsapi.php`, `https://football-data.co.uk/` (home), read 25 Nov 2026.

**The relationship, precisely.** The Football-Data.co.uk home page states: "My data is free, but for those who need access to more via a subscription API service, I am now partnering with TheStatsAPI." A dedicated page on the same site promotes the service. That is **evidence of a partnership and of active promotion by the site's owner**. It is **not** evidence of common ownership, and **not** evidence of shared data lineage: no statement on either site says the datasets are the same, derived from one another, or maintained by the same entity. Treating them as one source would be an inference the evidence does not support, and treating TheStatsAPI as independent of Football-Data.co.uk's restrictions would be equally unsupported. Both directions are recorded as open questions.

**Coverage and price.** TheStatsAPI advertises 1,000+ competitions, 84,000+ players and 10+ years of history, with xG and bookmaker odds bundled; pricing is quoted from roughly $50/month on a competitor's comparison page and its own site advertises 150 competitions with up to 1,196 on request. Prices are marketing claims and must be confirmed.

**Rights.** The service's terms restrict caching beyond what is needed to operate an application, which is incompatible with building a historical corpus, and prohibit resale. No training rights are stated.

**Verdict.** UNKNOWN for training, and structurally poor for a corpus because of the caching restriction. Not production-approved.

### 4.8 Sportradar — CONDITIONAL, enterprise only, with a retention problem

**Sources.** `https://www.sportradar.com/`, its data-licensing contact route, read 25 Nov 2026. No public pricing.

**What it is.** The largest commercial sports data supplier, with official relationships in some competitions and deep historical and odds coverage.

**Rights.** Licensing is contractual and negotiated. The published posture of enterprise sports-data contracts includes an obligation to destroy licensed historical data on termination and to certify the destruction in writing. That is directly hostile to our requirement to retain trained models indefinitely, because a model trained on data we must delete is a derived artifact whose own retention must be negotiated explicitly. Nothing in public material grants that.

**Verdict.** CONDITIONAL and expensive. Only worth a conversation if we ever need official-rights data for a regulated market, and only with explicit model-retention terms.

### 4.9 Sports Reference (FBref, Stathead) — PROHIBITED

**Sources.** Sports Reference terms of use and Stathead terms, read 25 Nov 2026.

**The restriction.** The terms prohibit use of the data "for purposes of training, fine-tuning, prompting, or instructing artificial intelligence models". In January 2026 advanced xG data was withdrawn from FBref after a data provider demanded its removal, which is a live demonstration that the page is a compilation of licensed third-party feeds rather than a rights holder's own data.

**Verdict.** PROHIBITED. No adapter, no manual corpus, no derived features from this source.

### 4.10 SofaScore — PROHIBITED for automated acquisition, everything else UNKNOWN

**Sources.** `https://www.sofascore.com/terms-and-conditions`, read 25 Nov 2026 via indexed text. The page is JavaScript-rendered and the Internet Archive copy returns 404, so the full body was not retrieved.

**The restriction, quoted from the indexed text.** "Using website content by embedding, aggregating, scraping or reproducing it without express consent is prohibited, unless permitted..." The site has no public data-licensing programme, and its internal API is undocumented and actively rate-limits or blocks automated clients.

**Evidence quality.** Because the body could not be read directly, this is a strong but not first-hand quotation. It is enough to refuse automated acquisition; it is not enough to characterise every other right, which stays UNKNOWN rather than being filled in by assumption.

**Verdict.** PROHIBITED for scraping. No account, no adapter, no negotiation.

### 4.11 Other providers considered briefly

* **BALLDONTLIE** (`https://epl.balldontlie.io/`): Premier League and related data from 2010 with a free tier. Terms not reviewed; UNKNOWN, and single-league.
* **Kaggle football datasets**: thousands of uploads, almost all of unknown provenance, often scraped from the sources prohibited above. UNKNOWN by construction, and unusable for production because the licence on an upload does not cure the rights of whoever first collected it.
* **API-Sports** (parent of API-Football): same terms as 4.4.
* **Wikipedia / Wikidata**: CC BY-SA for text, CC0 for structured data, but coverage is editorial rather than match-level and unsuitable as a primary results source.

---

## 5. Rights matrix

Statuses are exactly `PERMITTED`, `CONDITIONAL`, `PROHIBITED`, `UNKNOWN`. "CONDITIONAL" means a written agreement or approval is required; "UNKNOWN" means the evidence does not establish the right, which for planning purposes is treated as a no.

| Right | OpenFootball | Football-Data.co.uk | StatsBomb Open | API-Football | Sportmonks | football-data.org | TheStatsAPI | Sportradar | Sports Reference | SofaScore |
|---|---|---|---|---|---|---|---|---|---|---|
| Research use | **PERMITTED** | CONDITIONAL | **PERMITTED** | CONDITIONAL | CONDITIONAL | CONDITIONAL | CONDITIONAL | CONDITIONAL | PROHIBITED (AI) | UNKNOWN |
| Automated acquisition | **PERMITTED** | PROHIBITED | **PERMITTED** | **PERMITTED** | PERMITTED | **PERMITTED** | PERMITTED | CONDITIONAL | PROHIBITED | PROHIBITED |
| Historical data retention | **PERMITTED** | UNKNOWN | UNKNOWN | UNKNOWN | CONDITIONAL | UNKNOWN | PROHIBITED (caching limit) | CONDITIONAL | PROHIBITED | UNKNOWN |
| ML training / fine-tuning | **PERMITTED** | PROHIBITED | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | CONDITIONAL | PROHIBITED | UNKNOWN |
| Validation / evaluation | **PERMITTED** | PROHIBITED | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | CONDITIONAL | PROHIBITED | UNKNOWN |
| Derived features and model outputs | **PERMITTED** | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | CONDITIONAL | PROHIBITED | UNKNOWN |
| Trained-model retention after cancellation | **PERMITTED** | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | CONDITIONAL (destruction obligation) | PROHIBITED | UNKNOWN |
| Commercial deployment | **PERMITTED** | PROHIBITED | PROHIBITED (open terms) | UNKNOWN | CONDITIONAL | CONDITIONAL | UNKNOWN | CONDITIONAL | PROHIBITED | UNKNOWN |
| Redistribution of raw data | **PERMITTED** | PROHIBITED | PROHIBITED | PROHIBITED | PROHIBITED (absent consent) | PROHIBITED | PROHIBITED | CONDITIONAL | PROHIBITED | PROHIBITED |

Two readings matter. First, no column is green except OpenFootball's, and even that column stops at data: league marks and crests are outside it. Second, "CONDITIONAL" and "UNKNOWN" are not close to each other operationally: a CONDITIONAL right has a known path (a contract), an UNKNOWN one does not yet have a shape.

---

## 6. Historical coverage and technical comparison

| | OpenFootball | Football-Data.co.uk | StatsBomb Open | API-Football | Sportmonks | football-data.org | TheStatsAPI |
|---|---|---|---|---|---|---|---|
| Competitions | Major leagues, international tournaments | Up to 22 European divisions | Curated set (~10 competitions) | 1,000+ incl. cups | 2,200+ leagues (Enterprise) | ~12 free tier, more paid | 150 listed, up to 1,196 on request |
| Depth | Long for big leagues, uneven elsewhere | 1993/94 onward; stats from 2000/01 | Selected tournaments, 1958 onward in places | 2008 onward, usable from 2010 | ~2010 onward | A few seasons | 10+ years claimed |
| Fixtures / results | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| Team statistics | No | Yes from 2000/01 | Event-derived | Yes | Yes | Partial | Yes |
| Player statistics | No | No | Yes (events) | Yes | Yes | Squads only | Yes |
| Event-level | No | No | Yes (with xG) | Yes | Yes | No | Partial |
| Lineups / substitutions | No | No | Yes | Yes | Yes | No | Yes |
| Injuries / suspensions | No | No | No | Yes | Yes | No | Claimed |
| Odds | No | Yes, incl. closing | No | Yes (pre-match) | Yes | Limited | Yes, bundled |
| Odds timestamps | n/a | Collection day only (Friday), no per-snapshot time | n/a | Response-time only | Per-snapshot fields | No | Claimed |
| Corrections history | Git history of the repo | None published | None published | None published | None published | None published | None published |
| Export format | Text / JSON in git | CSV | JSON | JSON | JSON | JSON | JSON |

**On timestamps, which decide whether a model can be trusted.** Our temporal contract needs `available_at` per piece of information. Only the event-level providers (StatsBomb, API-Football, Sportmonks) expose per-snapshot odds times or event times. Football-Data.co.uk gives a *collection day*, not a time, and OpenFootball gives no availability information at all, so any corpus built from it must derive `available_at` under the explicit rule in section 4.2.1 and record the derivation, not just the result. That is acceptable for research and must not be dressed up as production-grade timestamping.
---

## 7. Pricing and cost scenarios (nothing purchased)

All figures are as published or as reported by a secondary source on 25 Nov 2026, in the currency the provider quotes. None has been verified by a quote.

| Provider | Published pricing | Basis |
|---|---|---|
| OpenFootball | €0 | CC0, no account |
| football-data.co.uk | €0 | Free CSVs, but PROHIBITED for our use |
| StatsBomb Open Data | €0 | Research licence |
| football-data.org | Free tier; paid tiers published per plan | Requests/minute and competition count |
| API-Football | Free 100 requests/day; paid tiers from roughly $16–19/month reported, with larger plans above | Daily request quota |
| TheStatsAPI | From roughly $50/month (secondary source); site advertises request pools | Monthly request pool |
| Sportmonks | €249/month reported for 120 leagues at 3,000 calls/entity/hour (secondary); Enterprise quoted | Plan + league count |
| StatsBomb commercial | No public price | Negotiated |
| Sportradar | No public price | Negotiated |

**Scenario A — research only, zero spend.** OpenFootball corpus, all baselines, all backtests, no odds and no event data. This is the scenario the recommendation adopts.

**Scenario B — research plus a paid API for cross-checks.** Add one small paid tier (API-Football or football-data.org) at roughly $20/month for fixture cross-validation. Only worth it once a written answer on training exists; otherwise it buys access we may not use.

**Scenario C — production-grade corpus.** Sportmonks Enterprise or StatsBomb commercial, plus a legal review of the contract, plausibly €250–1,000+/month before any legal cost. This is a Phase 3 decision with a written agreement, not a Phase 2B one.

**Hidden costs, all real.** Contract review time; engineering for a second provider's schema and ID mapping; the cost of rebuilding the corpus if a provider changes terms; and the cost of deleting models if a licence requires data destruction on exit. The last one is the expensive mistake: it is cheaper to establish model-retention rights before training than to retrain afterwards.

---

## 8. Unresolved licensing questions requiring written answers

Each question below is phrased so a vendor can answer it in one line, and each is UNKNOWN in section 5 until answered in writing.

**For every candidate provider:**

1. May we store your historical data indefinitely in our own database for model development, and must we delete it if we stop subscribing?
2. May we use the data to train, fine-tune, validate and evaluate statistical and machine-learning models?
3. May we retain the resulting model weights and derived parameters indefinitely, including after cancellation?
4. May we use model outputs (probabilities, ratings, expected goals) in a commercial product, and do you claim any right in those outputs?
5. Do you hold the necessary rights for every competition you supply, or are some feeds sub-licensed from third parties with additional restrictions?
6. May we publish aggregate research findings and derived metrics without publishing your raw records?

**Provider-specific:**

7. **Sportmonks:** does an Enterprise agreement expressly permit model training and indefinite model retention, given Articles 5.4, 5.6, 6.2 and 6.3 of the general terms? What are the exact rate limits per plan, in requests per minute and per hour?
8. **API-Football:** what is the earliest season with complete results for our target competitions, what is the per-minute ceiling on each plan, and does any term permit training? (Their public docs return 403 to automated clients.)
9. **TheStatsAPI:** is your dataset independent of Football-Data.co.uk's compilation, or derived from it? Does the caching restriction in your terms permit a persistent historical corpus? Is model training permitted?
10. **football-data.org:** do your terms permit creating a training corpus and retaining trained models, on free and on paid tiers?
11. **StatsBomb:** for Open Data, does the user agreement permit training models and retaining weights, and does it permit commercial use of derived outputs? For commercial, the same two questions in the contract.
12. **Sportradar:** can model-retention rights survive the contractual destruction obligation, and at what price?

No vendor has been contacted. These questions are for the CEO to authorise, and should be sent only to providers we would actually use.

---

## 9. Provider provenance and dependency risks

* **Compilation versus ownership.** Most "providers" are compilers. Football-Data.co.uk assembles bookmaker prices; Sports Reference assembles third-party feeds and lost xG when a supplier objected; TheStatsAPI resells aggregated stats. Permission from a compiler does not bind the original rights holder, and an indemnity from a compiler is only as good as the compiler.
* **The Football-Data.co.uk / TheStatsAPI relationship.** A stated partnership and prominent cross-promotion, with no published statement about data lineage. Two risks follow in opposite directions: if the datasets are related, TheStatsAPI inherits the AI-training restriction; if they are independent, TheStatsAPI's own caching and resale terms still block a corpus. Both paths lead away from using it without written answers.
* **Single-maintainer sources.** Football-Data.co.uk is one person's project and OpenFootball is volunteer-maintained. Either can stop, change format or disappear. A corpus built on either needs its own immutable copy with a content hash, which our manifest already provides.
* **Terms drift.** Sports Reference's January 2026 removal shows terms and data can change under a live dependency. Any production corpus needs a pinned snapshot, a recorded licence version with a date, and a re-check cadence.
* **Competition rights.** None of the assessed providers is an official rights holder for the competitions it covers, and Sportmonks says so explicitly. Anything public-facing that uses league names, marks or crests needs its own analysis, separate from data licensing.
* **Model-retention asymmetry.** Data licences are usually written for applications, not models. A licence can permit serving predictions while forbidding the artifact that produces them, and the destruction clauses in enterprise contracts make that concrete.

---

## 10. Recommended acquisition strategy

**Two tiers, physically separate, never merged silently.**

**Tier R — research corpus.** Sources whose rights permit research and, where possible, training: OpenFootball now; StatsBomb Open Data only inside an isolated sandbox that never feeds a production corpus. Lives in a gitignored data directory, manifests carry `productionEligible: false`, and nothing derived from it is published.

**Tier P — production-eligible corpus.** Reaching this tier needs four separate gates passed, in order, and passing one does not imply the next:

| Gate | Question | Who decides | Current state for OpenFootball |
|---|---|---|---|
| 1. Legal permission | Does the licence allow this use? | Source licence | **Passed.** CC0, irrevocable, covers storage, training, commercial use and redistribution |
| 2. Dataset eligibility | Does the manifest carry verified provenance, the derivation rule and complete scan evidence? | Our evidence rules | **Not yet.** No OpenFootball dataset exists; the 4.2.1 fields are unimplemented |
| 3. Internal production approval | Has a named human approved this dataset for production use? | CEO, on the evidence record | **Not sought** |
| 4. Publication and deployment | May the artifact be published, shipped or served to Ron? | Separate authorisation, per artifact | **Not sought** |

So CC0 makes OpenFootball *legally* usable for commercial work, and that is the whole of what it establishes. It does not make any dataset or trained model internally approved, and it authorises nothing about publication. Each dataset manifest must still record the licence name and URL, licence version date, the evidence reference (a stored document, not a link), the reviewer, the approved scope and the approval date. The Phase 1 machinery already refuses to grant production status from a CSV spec; the rule extends to every provider, and a public-domain source is no exception.

**Rules that follow from the matrix.**

1. One provider, one adapter, one manifest. No mixing of sources inside a single dataset version without recording which rows came from where.
2. `productionEligible` requires gates 1 to 3 above: a verified licence with an evidence reference, complete scan evidence, the 4.2.1 derivation fields, and a named human approver. It never authorises publication or deployment on its own, and a permissive licence alone never sets it.
3. Derived artifacts inherit the strictest licence of their inputs. A model trained on Tier R data is a Tier R artifact, full stop.
4. No provider is added because it is cheap. Cost is the last column, not the first.
5. Every provider gets a written-answer file before its adapter is written, so the code cannot outrun the rights.

---

## 11. Go / no-go recommendation

**GO — Phase 2B, OpenFootball research corpus.** Build an OpenFootball adapter on the existing provider-neutral architecture, ingest fixtures and results, derive `available_at` under the section 4.2.1 rule with all four derivation fields recorded, and train the three baselines the lab was designed for.

**Why research-only, when the licence permits more.** The corpus ships `productionEligible: false` by choice, not because CC0 is insufficient. Gates 2 to 4 in section 10 have not been passed: there is no evidence record, no derivation implementation and no human approval, and a research corpus is the correct way to earn them. The licence clears the legal question; the manifest, the reviewer and the CEO clear the rest.

**What OpenFootball can support:**

* Match outcome models (home/draw/away) with chronological walk-forward validation.
* Elo and team-strength ratings, including the `before=` leakage-safe path already proven in Ron.
* Dixon-Coles and independent Poisson, which need only results, dates and teams.
* Basic form features: recent points, goals for and against, rest days, home/away splits.
* Reproducible dataset versioning and calibration studies on probabilities.

**What it cannot support, and what that would cost to fix:**

* No odds: no market intelligence, no closing-line value, no bookmaker comparison. Needs a licensed odds source with per-snapshot timestamps.
* No xG or shot data: goals-based models only, with no shot-quality signal. Needs StatsBomb commercial or equivalent.
* No lineups, injuries or suspensions: no availability features. Needs a paid provider with those feeds.
* No event-level data: no tactical or player-level modelling. Needs a full event provider.
* No per-field availability timestamps: fine for research, insufficient for production pre-match prediction. Needs a provider that timestamps its snapshots.

**NO-GO — any training on football-data.co.uk, Sports Reference or SofaScore.** These are explicit prohibitions, not gaps.

**HOLD — API-Football, football-data.org, TheStatsAPI, Sportmonks, StatsBomb, Sportradar.** Each needs a written answer from section 8 before an adapter is written. Sportmonks is the most promising paid path because its Enterprise page already concedes storage, commercial use and historical seasons; training is the single missing sentence.

**Recommended Phase 2B scope, for approval:** one adapter (`openfootball`), one corpus, three baselines, one walk-forward evaluation, no odds, no production eligibility, no publication. That proves the training half of the lab on a clean legal footing while the vendor letters are drafted.

---

## Appendix — files, rights and reproduction

This document changes nothing in the pipeline. It sits alongside `docs/corpus.md` (the Phase 1 contract) and `docs/licensing-matrix.md` (the Phase 1 per-source matrix), which remains the operative gate for adapters; where this document is more detailed, it refines rather than replaces that matrix, and any conflict resolves in favour of the stricter reading.

Evidence base: provider terms, licence texts and documentation read on 25 November 2026, cited inline. Secondary sources are marked as such and never used alone to grant a right. Where a page was unreachable, the document says so and records the right as UNKNOWN rather than inferring permission.
