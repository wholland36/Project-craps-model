# Project Craps NCAA Men's Basketball Research

Status: **RESEARCH ONLY**. No approved $400 wagers.

Command: `python -m models.train_ncaab --output results/ncaab_men_research.json`

Python 3.11 dependencies: pandas, numpy, scikit-learn, requests, pyarrow.

Public source: sportsdataverse's NCAA men's basketball schedule parquet (season year is the **start** of the academic basketball season). Source is per-contest game dates, home/away identifiers, final scores and NCAA contest IDs. The code retrieves 2016–2025 seasons, excluding incomplete live 2026–27 results. Model never treats later score outcomes as pregame features.

**Methods:** Per-team rolling offense/defense, prior-game Elo difference, bounded rest, shrinking across season breaks; margin and total Ridge regressors fitted on seasons through Y-2; single-season pregame residual calibration on Y-1; untouched chronological Y holdout for 2022, 2023, 2024 and 2025. Reports Brier/log-loss against causal pregame Elo and historical home-win-rate baselines; spread/total mean absolute errors and synthetic threshold 3-way probabilities. Prior score updates for all games on the same UTC date happen only after features for that whole date have been saved. The synthetic spread/total threshold tests use **no** sportsbook odds and **cannot** establish expected betting ROI.

**Deployment blockers:** neutral-site designation and real home advantage; contemporaneous player transfer/rotation/injury information; possessions-adjusted efficiencies and pace; exact timestamped same-book pregame and closing quotes; paired no-vig baseline on identical dates; out-of-sample price-specific push-aware ROI and confidence intervals; calibrated 2026–27 live model; secure Google Sheets source-of-truth reconciliation and approved release. All require independent verification and successful tests.

Keep the canonical private Google Sheet's official wagers untouched. An archived run artifact is a research report, not a production bet signal.
