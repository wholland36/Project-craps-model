# NCAA football calibration challenger — November 9, 2026

**Built, fitted, frozen and running as a separate research challenger. No model promoted. Approved live risk: $0.**

Version: `ncaaf-temperature-v1-20261109`. Branch: `research/ncaaf-calibration-20261109`, based on public-audit commit `700dbc538df929821953af6e365fde8c7369c440`. Exact final commit is in the accompanying output COMMIT_RECEIPT.json. Official release 2026-11-03-v1, canonical Google Sheet, historical wagers and immutable forecasts remain unchanged. Frozen v1 missing-record integrity stop remains unresolved and is not bypassed.

## What was fitted

One independent, symmetric temperature slope per market, no intercept or sportsbook probability as a feature. For W/P/L, conditional c=W/(W+L) becomes logistic(slope*logit(c)); original push mass is retained. Slopes are constrained to [0,5], with fixed ridge penalty 0.5*(slope-1)^2. Fit uses weighted conditional nonpush logloss on 2022–2023 only. Each event contributes one unit of weight per market, divided among its same-book line observations; only home/over is fitted, avoiding complementary duplicates. These are unvalidated design choices, not guaranteed improvements.

Protocol was written before fitting. Code, protocol, exported coefficients and official parent hash were registered before assessment and future capture. No refits or selection among alternate challengers are scheduled. Exact 0/1 probabilities remain exact under positive slopes; slope zero maps conditional p to .5. Fit endpoint features use 1e-12 solely for optimization; evaluation does not hide infinite logloss. Push probability is not recalibrated. Separate market transforms have no coherent joint-score or cross-line probability certificate.

|Market|Frozen slope|Training nonpush games|Interpretation|
|---|---:|---:|---|
|moneyline|0.8039466492|1480|Modest reduction in confidence; benefit unvalidated.|
|spread|0.0000000000|1484|Boundary solution: 50/50 conditional probability; no directional ranking information.|
|total|0.0000000000|1485|Boundary solution: 50/50 conditional probability; no directional ranking information.|

The spread/total zero slopes are retained, not replaced with an unconstrained negative slope. They are evidence that the fitted training relationship did not support positive confidence ordering under this specification. A flat .5 prediction is a diagnostic comparator, not a trading advantage. No roster/QB/weather coefficients were added without verified training evidence.

## Executed development assessment

The saved 2024–2025 historical folds were already examined. This assessment cannot reset them to an untouched holdout. Input SHA256 is `5cf5b1a5e78612aad8b78a76e0c8e66735c495324d46cb6fa78ea505d36404c2`. Historical input forecasts are saved rolling-architecture-fold reconstructions, not original contemporaneous betting probabilities or the November 3 official model applied backward. Historical availability/publication timing remains unauthenticated.

Values below weight games equally within each market and use only home/over, so they intentionally differ from the prior all-quote/complementary-side summaries. Winner Elo is independently reconstructed from saved pregame feature history, not sportsbook prices. No Elo spread/total distributions are invented.

|Season|Market|Games|Parent Brier|Challenger Brier|Same-book no-vig Brier|Winner Elo Brier|Paired challenger-minus-parent 95% interval|
|---|---|---:|---:|---:|---:|---:|---|
|2024|moneyline|754|0.20832|0.20728|0.18813|0.22663|-0.00323 to 0.00091|
|2024|spread|770|0.28021|0.25000|0.24921|unavailable|-0.04038 to -0.01899|
|2024|total|770|0.24930|0.25000|0.24963|unavailable|-0.00583 to 0.00687|
|2025|moneyline|755|0.19325|0.19541|0.18034|0.21456|0.00030 to 0.00395|
|2025|spread|776|0.26463|0.25000|0.24970|unavailable|-0.02545 to -0.00438|
|2025|total|776|0.25338|0.25000|0.25004|unavailable|-0.00907 to 0.00256|

Lower Brier is better. Moneyline improved slightly in 2024 but worsened in 2025; it remained behind no-vig in both. Flattening spreads improved on the parent but remained slightly worse than no-vig. Totals worsened in 2024 and improved in 2025, with intervals spanning zero. There is no consistent validated improvement or production edge.

Paired intervals use 1,000 resamples of game-level means, seed 20261109; they are descriptive and omit week/season dependence, multiplicity and prior inspection/selection effects. DEVELOPMENT_RESULTS.json also contains push-inclusive three-way Brier, exact infinite-logloss counts, quote-weighted push-aware hypothetical ROI, selected counts, drawdowns and event-cluster ROI intervals for parent and challenger. None of the six assessed market/year cells had infinite logloss, but future exact support failures remain reportable. Historical ROI is one unit per selected book/line quote, not an executable portfolio; drawdown orders event aggregates by kickoff. No independently authenticated CLV or actual wagers are claimed.

## Prospective pilot executed

After registration, a fresh free parent shadow capture saved 9 reference pairs across 3 future games. The challenger registered 9 first event/book/market/line predictions across those same 3 games, with zero settlements and no refusals on the first run. Duplicate snapshots are not independent games. Parent source captures before calibration registration are excluded; forecasts cannot be created after kickoff. Future records include source/parent/model hashes, old feature cutoffs, both prices, no-vig references and parent/challenger probabilities.

All forecasts and final grades append to separately locked hash-chain journals. Final grading preserves exact team, kickoff and neutral-site identity; score/identity revisions append quarantines and exclude their prior grades from summaries. Provider final scores and quote scopes remain unauthenticated, so grades are descriptive under the recorded scope assumption. No automatic production qualification or Kelly allocation runs. Original source/forecast artifacts remain untouched.

The future parent is a newly computed point kernel from official first means, whereas the historical calibrator input was rolling-fold model output. This historical-to-future transport is unvalidated and stays explicit. Parent feature cutoffs are old; fresh source capture does not imply refreshed model features. Independent current winner Elo remains unavailable in this forward source; it stays null. QB/roster/eligibility/replacement workload/weather, original market update time, settlement scope, book jurisdiction and executable prices remain missing or unauthenticated.

Existing half-hour main-chat automation now runs the calibration entry after the public shadow capture. Routine mode verifies registered code, model, protocol, official-parent and input journals, never fits. It appends future captures and exact-identity provider finals; failures and quarantines remain visible. It reports material changes and stays quiet on unchanged pending runs. All pilot records are excluded from future powered confirmation; confirmation remains closed until a separately authorized preregistered sample/power/cluster design exists.

## Decision and next work

|Market|Decision|Next useful step|
|---|---|---|
|Moneyline|RESEARCH ONLY / NO-GO|Keep fixed calibration through the pilot; test whether the historical-to-live transfer helps on new games. Do not select it because of one improved year.|
|Spread|RESEARCH ONLY / NO-GO|Treat flat .5 as a diagnostic. Investigate margin distribution and input reliability in separately authorized development before adding features or a new challenger.|
|Total|RESEARCH ONLY / NO-GO|Retain mixed evidence; investigate score-total residuals and authenticated pace/weather context before a separately registered change.|

For a real wager, independent validation and explicit production authorization are still required, followed by complete date-aware input qualification and a fresh executable exact event/book/market/side/line/price from an available legal book. Hard Rock requires Florida identity. Recompute the configured fractional-Kelly allocation on that exact price with risk caps; archived/reference quotes cannot authorize risk. No default model, canonical record or $400 official unit was changed.

## Reproduce without changing frozen state

Use validation-venv Python from the repository root. `research.ncaaf_calibration fit` accepts a **new** state directory only, verifies the saved private archive and fold hashes, writes its protocol, fits once and freezes its coefficients; never rerun fit against the registered state. `research.ncaaf_calibration_report` reproduces paired development intervals without fitting. `research.ncaaf_calibration run --state STATE --parent PUBLIC_SHADOW_STATE --output UNIQUE_JSON` verifies and captures/grades prospectively. Outputs refuse overwrite. Exact model, protocol, registration, source and code hashes are in SOURCE_MANIFEST.json. The original purchased archive stays private; no new paid requests, purchases, bets, tuning or refits occurred beyond this explicitly authorized initial calibration fit.

Tests: 21 passed across calibration, public-market and existing market-audit tests. Cases include preserved push mass and complements, monotone ordering, endpoint infinite loss, invalid vectors/slopes, duplicated quote weighting, first-capture idempotence, no late backfill, final grading, persistent score-revision quarantine, paired quote integrity and journal tamper detection.
