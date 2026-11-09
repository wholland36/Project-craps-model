# NCAA football public-market validation — November 9, 2026

**Moneyline: NO-GO. Spread: NO-GO. Total: NO-GO. Research only; approved live risk $0.**

Executed on branch `research/ncaaf-public-quotes-20261109`, based on `14c872f3a8476eb07ef7391f89cdfb97bcd42f01`. Exact final commit is recorded in COMMIT_RECEIPT.json. Existing market checker and frozen engines were not edited. Official model/code/runtime hashes and beta v2 entry/algorithm/bundle checks passed. Frozen v1 remains stopped for its previously missing journal record; this study neither repairs nor bypasses it.

## Public sample: actual retrieval and rows

Attribution: [The Odds Gap](https://theoddsgap.com/data). HTTPS download succeeded without credentials: HTTP 200, 127,914,171 bytes, SHA256 `735439fbe38e85d76e5a0e05224c9ad3299cd4c883be2385b4adb8a0419f7b94`. The free response headers identify sample access and the October 19–25 window. The first team-results request using `league=ncaaf` returned HTTP 400; the documented `college-football` league returned HTTP 200 and 112 team rows. Both receipts are preserved. No purchase or paid request occurred.

Actual odds: 581,452 rows, 117 provider event IDs, 20 book/exchange keys; 290,726 structurally complementary primary-side pairs. Raw row counts: moneyline 196,904; spread 192,556; total 191,992. Hard Rock-attributed rows: 34,962; jurisdiction is absent. Repeated scans, opposing sides and event suffixes are not independent games.

Observed scan range: 2026-10-19T04:00:30.350526+00:00 through 2026-10-26T03:00:30.193001+00:00. Kickoffs extend to 2026-11-01T03:00:00Z; 61 event IDs have a kickoff outside the advertised Eastern game-date week. Headers include a 250,000 source-row cap while 581,452 exported side rows were received; internal cap semantics and universe completeness are unverified. No X-Next-Start was returned. Do not infer exhaustive coverage.

There are 11,925 last-within-sample event/book/market/line pairs. Last-within-sample is not certified closing: median age is 2009.3 minutes before scheduled kickoff. The raw data have 54 IDs with more than one team/kickoff identity; all are quarantined, even when one version matches the result. Initial permissive exact joins gave 48 matches, but the final strict all-revision policy leaves **2 result-matched games**. Exclusions and all raw evidence remain retained.

Example inspected row: first scan 2026-10-19T04:00:30.350526+00:00; Texas A&M at Alabama, scheduled 2026-10-24T19:30Z; DraftKings home moneyline -675, opposite +490; home spread -14.5 at -108. Provider ID ends `-g2`; it is not accepted as proof of an actual football doubleheader. Original rows are in local odds.raw, not committed.

The independent no-vig calculation uses each book’s own simultaneous opposing pair and proportional normalization; provider devig_fair_prob uses a different advertised power method and is never copied as model p. Scan time is provider-reported collection time, not an authenticated sportsbook update. Settlement scope, availability, limits, jurisdiction, result authenticity and final-update completeness remain unverified. Treat the two-game market Brier table as a provider-score QA diagnostic, not independent model validation.

**No sample model ROI, model Brier, or model-vs-market advantage is claimed:** zero eligible original pregame model probabilities were joined. This sample precedes the November 3 official release. Applying later-fit coefficients backward would introduce leakage. Pregame Elo for the sample is unavailable; spread/total Elo distributions are unavailable. Missing fields remain null.

[Terms reviewed](https://theoddsgap.com/terms): research/modeling use requires attribution; resale, feed repackaging and sustained scraping are restricted. The adjacent bulk-reuse clause requests prior contact; heavier/commercial reuse is not cleared here. The one-time sample stays local; no raw quote feed is published. Underlying licensed feeds and provider attribution are not independently authenticated.

## Purchased historical archive: executed replay

Used the already purchased private The Odds API archive in the local Work runtime. Rechecked all 328 cached snapshot raw and normalized-file hashes against the existing manifest; no credential was read or API request made. This is cached-access availability, not a new subscription entitlement check. Replayed every saved joined row through research.market_audit.checked: 227,030 accepted, zero checker rejections, 3,031 games. Source universe: 3,132 FBS–FBS games; 101 lack every market. All missing-market counts remain in chronological-replay.json.

Saved chronological model folds use prior seasons and were already reconstructed/examined on November 5. They are frozen historical architecture folds, **not** the frozen November 3 default applied backward, not new training, and not original issued forecasts. Simulated cutoffs do not authenticate feature publication/score availability. No new untouched holdout exists in 2022–2025.

Recomputed season/market metrics reproduce the archived results within 1e-10. Added 174 season/market/book summaries with actual book-specific prices, same-event same-line opposing pairs, push-aware returns, event-cluster confidence intervals and drawdowns. Winner Elo is recomputed from saved source-game historical_features, independently of book prices; paired-quote Elo Brier is included for moneylines. No invented Elo spread/total distribution.

|Season|Market|Games|Model Brier|No-vig Brier|Hypothetical ROI|95% event-cluster ROI interval|Max drawdown units|
|---|---|---:|---:|---:|---:|---|---:|
|2022|moneyline|720|0.2211|0.1981|17.9%|0.2% to 36.9%|439.15|
|2022|spread|722|0.2821|0.2502|-4.8%|-13.0% to 3.2%|645.30|
|2022|total|722|0.2720|0.2501|-8.7%|-16.3% to 0.6%|974.69|
|2023|moneyline|760|0.2031|0.1786|-14.0%|-25.9% to -0.4%|1115.28|
|2023|spread|763|0.2831|0.2500|-7.8%|-15.2% to -0.2%|709.90|
|2023|total|763|0.2623|0.2500|-1.6%|-9.5% to 6.0%|327.48|
|2024|moneyline|754|0.2096|0.1902|-10.0%|-21.7% to 4.4%|667.59|
|2024|spread|770|0.2795|0.2495|-9.9%|-17.6% to -1.5%|613.04|
|2024|total|770|0.2488|0.2497|9.2%|0.2% to 18.6%|94.36|
|2025|moneyline|755|0.1972|0.1841|-8.0%|-20.8% to 6.3%|475.63|
|2025|spread|776|0.2639|0.2500|-2.1%|-9.7% to 5.5%|339.59|
|2025|total|776|0.2536|0.2501|3.1%|-5.6% to 12.0%|117.99|

Brier excludes observed pushes and compares conditional nonpush probabilities. A push refunds the risked unit and remains in the ROI stake denominator. Model selection remains the existing fixed thresholds: 2.5 percentage points spread, 3 points total/moneyline, plus positive push-aware expected value. No tuning. ROI is one unit on each qualifying archived quote, including correlated books and complementary tickets; it is not a best-price executable portfolio. Drawdown aggregates tickets by event and orders by kickoff, not known settlement clocks. CIs use 1,000 event-cluster resamples, seed 20261109; they do not capture cross-game week/season dependence or selection bias. Every sparse book subgroup is retained with its denominator. No authenticated CLV is available.

Correction to the November 6 prose: model Brier is worse than no-vig in **11/12**, not 12/12 cells; 2024 totals are slightly better. This isolated already-examined result does not clear validation.

## Prospective process executed and scheduled

A separately registered append-only journal now captures free ESPN-attributed candidate quotes before kickoff. First and registered verification runs each captured 3 future games and 9 reference pairs, no failures. These repeated runs are not six games. The first capture preceded code registration and is marked exploratory; all pilot records remain excluded from confirmation. Exclusive record files, a locked hash-chain journal, raw sources, source hashes, identities, receipt times and parent-forecast digests are retained in private state `ncaaf-public-shadow-20261109`. Registration pins this additive code plus its reused checker and reference helpers; drift stops it. New records never overwrite first forecasts.

When an exact immutable official first-mean reference matches the event, a newly issued point-kernel shadow is calculated from that reference. It retains the old feature cutoff and is explicitly not the original model betting probability. No stale v1 record is used. Source-only candidates remain available where a parent reference is missing. Unknown quote update time/scope, unverified QB/roster/workload/weather and executable-book evidence all remain blockers. Existing half-hour main-chat automation now runs the additive capture after ncaaf_next and keeps unchanged routine work quiet. No extra paid data calls were scheduled.

Future grading must append an exact-identity independently reconciled final result, preserve all revision quarantines and feed eligible joined rows through market_audit. Existing study monitors remain in force; this pilot does not open powered confirmation. Results are descriptive until a separately authorized power/cluster design is frozen.

## Production readiness, by market

|Market|Decision|Specific blockers|
|---|---|---|
|Moneyline|NO-GO|No original sample forecasts; historical model scores trail no-vig in all four years; independently authenticated quote/feature timing and new confirmation absent.|
|Spread|NO-GO|Historical model trails no-vig in all four years; line/scope/source authentication incomplete; no calibrated independent Elo margin distribution; prospective power design absent.|
|Total|NO-GO|Mixed examined ROI and only one better Brier year; sample identity revisions; weather/roster/timing evidence incomplete; no independent Elo total distribution or new confirmation.|

For any eventual real wager, first require independent validation plus Wade’s explicit production authorization. Retrieve a fresh executable quote from an available legal book, authenticate jurisdiction (Hard Rock Florida for Hard Rock), and match exact event, market, side, line, price and overtime/push rules. Rerun date-aware Project Craps input/qualification gates and the configured fractional-Kelly sizing against that exact price with portfolio caps. With decimal-profit b and W/P/L masses, full Kelly is (b*W-L)/(b*(W+L)), floored at zero before the authorized fraction/caps. No new Kelly fraction is invented here. Historical or public reference prices cannot authorize a stake. Canonical Sheet, historical wagers, immutable forecasts and official $400 unit / 13–8 / estimated $7,705.48 baseline are untouched. Approved risk remains $0.

## Reproduction

Use the existing validation-venv Python from the repository root. Download into a new local folder with `-m research.ingest.odds_gap_sample --output NEW_FOLDER`; receipts preserve HTTP errors and hashes with no automatic retries. Replay the pinned downloaded bytes with `-m research.public_market_validation public --odds FOLDER/odds.raw --results FOLDER/results-college.raw --output NEW_JSON`. Run the archive replay with `-m research.public_market_validation replay --input PRIVATE_ARCHIVE/joined-retrospective-quotes.jsonl --original-report ORIGINAL_VALIDATION_JSON --source-snapshot SAVED_SNAPSHOT --output NEW_JSON`. Inputs and output must remain separate; outputs refuse overwrite. See SOURCE_MANIFEST.json for exact local source hashes and paths in the existing runtime, and chronological-replay.json / season-market-book-results.csv for all computed results. Tests: `-m unittest tests.test_market_audit tests.test_public_market_validation` — 14 passed. No training jobs, purchases, bets or production promotion.
