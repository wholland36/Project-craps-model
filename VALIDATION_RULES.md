# Project Craps validation policy — v3 research gates (2026-10-31)

The canonical *placed-wager* ledger remains the Google Sheet; this public repository must never contain personal wagers, secrets, or screenshots.

## Model development and release gates

1. Separate NCAAF FBS, NFL, and all other sports. A passing test in one sport never validates another.
2. Construct immutable pregame features from games and information available strictly before the forecast time. Same-day results cannot update later game predictions without an explicit verified timestamp. Preserve game ID and observed date.
3. Fit exclusively on chronological training seasons; choose hyperparameters and calibrate on earlier validation seasons; freeze then test untouched later seasons. Prefer rolling-origin validation over one lucky season.
4. Evaluate home-win, spread and total probabilities independently, including integer-line pushes, calibration buckets, Brier, log loss, baseline comparisons and season-by-season variation. Never classify score-fit alone as a betting edge.
5. Compare against strong benchmarks: historical home rate, independently computed pregame Elo, and contemporaneous no-vig bookmaker predictions. Quantify uncertainty of differences; do not assume a tiny difference is a meaningful improvement.
6. Historical betting simulations require timestamped sportsbook book ID, market, selection, spread/total line and actual juice, available before kickoff. Grade individual quotes without cross-book substitution. Report coverage, stake-exposure, ROI, CLV only when same-book closes are verifiable, drawdown, and confidence intervals. Avoid selecting thresholds on the test season.
7. Handle injury/QB/roster, weather, possessions, explosive-play tails and market disagreement uncertainty; missing material inputs trigger data-quality downgrades or PASS, never invented model precision.
8. Before production, demonstrate robust forward-chaining, materially improved holdout calibration versus relevant baselines, stable result across seasons and risk-adjusted betting performance; otherwise retain RESEARCH ONLY.
9. Production forecasts must include as-of ET, frozen model version, data vintage/provenance, exact event ID, outcome definition, book/price, p, fair line, break-even, uncertainty, edge, EV and price cutoff. If unavailable, mark NOT_COMPUTED and APPROVED_RISK=0.
10. Spread qualifier requires 2–2.5 percentage point adjusted edge above price break-even; total 2.5–3pp; moneyline >=3pp. Integer pushes require 3-way W/P/L EV calculation. Use conservative fractional Kelly, correlated-portfolio caps and current bankroll; a $400 unit is a sizing convention, not an automatic commitment. Prefer 0–3 plays, no forced bet.
11. Official wager placement requires explicit user confirmation. Maintain one immutable canonical cross-chat ledger, don't backfill original p/EV, never overwrite historical stakes, don't double-grade settled tickets, and never conflate research candidates with placements.
12. No automatic model promotion. A challenger must outperform the frozen champion on chronologically isolated data with adequate sample size. Document failure modes, reproducible commits and archived artifacts before releasing.
