# NCAA football trap games momentum and player availability

This is an executable research feature layer on the November 5 validation branch. It does not change the frozen official model or the completed validation results. Trap and momentum coefficients are not fitted, so these features do not yet move a live prediction. The earlier official model used rolling scoring/Elo/rest features; its injury collector archived reports and returned `injury_adjustment: NOT_COMPUTED`.

## Trap game definition

AP Top 25 is the default poll. For each team, flag a game against an unranked opponent immediately before a game against a currently ranked opponent, or immediately after a completed game against an opponent ranked before that previous game. Record the two flags separately. A sandwich game may have both flags. A bye does not count as a game; adjacency stops at the season boundary. The team's own rank is irrelevant. Unknown poll coverage is unknown, not unranked.

The next opponent uses the poll available at the forecast cutoff, never a future game-week ranking. The previous opponent uses its pregame poll. Require a complete poll covering all top-25 slots (including legitimate competition ties), publication/observation times, validity interval and source hash. Schedule completeness and exact event identity are required. The flag describes a hypothesis; its sign and magnitude must be learned from training data. Do not automatically subtract points.

## Momentum

Keep features for both teams: wins and margins in the latest three completed games, plus changes against the preceding three. Strength-adjusted momentum uses the team's actual margin minus the independent pregame expected margin for each prior game. Winning by 10 when expected to win by 24 gives a -14 residual. Missing original expectations do not become zero. Fewer than six eligible games leaves the window-to-window trend unresolved. Only completed, observed same-season results are eligible.

The official rolling scoring and Elo features already contain some recent form. The separate ablations in `ncaaf_context_protocol.json` must show incremental value rather than count the same signal twice. Historical forecasts reconstructed now cannot be called original pregame forecasts.

## Player injuries

`injuries` accepts event-bound status reports and external player-versus-replacement values. Offensive value changes expected team scoring; defensive value changes points conceded. A quarterback and his named backup can have a different gap from a receiver and his replacement. Position labels alone do not supply a calibrated numerical value.

Adjust relative to availability already represented by the baseline. A player newly out from a full-availability baseline gets the full estimated replacement gap. An absence already fully embedded in the baseline gets no second deduction. Do not estimate baseline availability by assuming every historical team was fully healthy.

`injury_scenario` copies the baseline artifact, shifts its expected margin/total and recomputes its discrete W/P/L probabilities. It never edits the original coefficients. Unknown player values or incomplete availability coverage return `NOT_COMPUTED`. There is no arbitrary star penalty. Questionable/doubtful/limited statuses require a documented effective-availability estimate even for mean scenarios; uncertain statuses cannot produce a probability from an averaged mean shift. Use separate coherent active/out scenarios and validate their mixing policy before live use. Multiple-player additive effects and lineup interactions remain unvalidated.

The six-point QB and three-point defender examples in tests are synthetic sensitivity fixtures, not estimates for any actual player. No current player's injury impact has been estimated in this implementation.

## Use and status

Run `python -m research.ncaaf_context --input PRIVATE_INPUT.json --output NEW_PRIVATE_OUTPUT.json`. The input object supplies `event`, `schedule`, `polls`, `history`, `reports`, `asof` and optionally `roster_coverage_complete`. Functions and synthetic test fixtures define the required fields. Output creation refuses overwrite. Source hashes provide traceability, not independent authentication.

The current branch implements feature construction and confirmed-availability injury sensitivity. It has no ranking/injury ingestion adapter, fitted trap/momentum coefficients, fitted player-value model, or live-runner connection. Historical AP/availability source vintages and replacement-value estimates remain missing. The next model study must acquire those inputs, fit the registered ablations on earlier data and evaluate on untouched prospective forecasts. No production approval or updated historical performance is claimed.

November5quant review: the research poll validator now accepts legitimate competition ties, including tied25extending the ranked set. The previous unique-rank assumption rejected real preseasonAPdata. Original source-time guards and frozen official model remain unchanged. Retrospective trap results use a separate adapter with explicit unauthenticated publication/capture limitations.
