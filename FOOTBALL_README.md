# Football Model 2.1 executable research

`python -m models.train_football --sport NFL --output results/NFL_research.json`

`python -m models.train_football --sport NCAAF --output results/NCAAF_research.json`

Dependencies: Python 3.11, pandas, numpy, scikit-learn, requests.

Both commands retrieve real historical score schedules and construct rolling pregame team attack, defense and Elo features. Games played on the same date are isolated from one another to prevent leakage. Four chronological testing folds use seasons through Y-2 to fit, Y-1 for predictive residual calibration and Y for evaluation (2022–2025). Reports include home-win Brier/log-loss, Elo and historical home-rate benchmarks, NFL unverified no-vig market comparison where available, margin and total MAE, synthetic 3-way margin distributions and data limitations. **No betting profits or positive EV are claimed**: historical bookmaker price timestamps and other deployment gates are unverified.

`python -m unittest discover -s tests -v` verifies payoff/push behavior, correctly oriented margin outcomes, same-date feature isolation, snapshot idempotence and fail-closed deployment. Current research parameters are not to be deployed for live wagering. Independent forward-chained calibration and ROI confidence intervals against timestamped sportsbook offers, roster/QB/injury/weather vintages, production data pipelines and authorized release manifest must all be verified before risk > $0.

The live pregame snapshot interface is `python -m models.run_pregame --input quotes.json`. Quotes must be supplied as timestamped JSON. It generates append-only local research records, not writes into Google Sheets. The authoritative private canonical Sheet must remain separate.
