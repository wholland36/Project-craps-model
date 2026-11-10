# Three-sport validation development — November 10, 2026

**Executed for NFL, NCAA football and NCAA men’s basketball. All nine sport/market combinations remain RESEARCH_ONLY / NO_GO. Approved betting risk $0.**

Official release 2026-11-03-v1, v1/v2/v3 experiments, NCAA football calibration, immutable forecasts, wagers and canonical Google Sheet are unchanged. New work has its own code, fitted artifacts, source hashes, protocol, journals and branch. V1’s missing original forecast remains unresolved.

## What ran

The same `forecast` and `masses` functions generate historical replay and prospective predictions. The opponent-adjusted score model is fitted at quarterly origins using only results with a reconstructed 24-hour embargo. The first-boundary clock is one microsecond before the quarter so a midnight game remains pregame. This time convention does not establish original publication availability. All historical results are examined development.

A fixed rest/recent-form residual correction is the challenger. A score-only arm is its ablation comparator, not a model selected after looking at results. NCAAB uses prior box-estimated possessions and regulation pace. Player/QB/lineup/replacement workload, weather vintages, football drives and authenticated efficiency timing remain blocked. We did not manufacture these inputs.

The probability calculation resamples paired earlier out-of-fold score errors, retaining score correlation and integer pushes. A fixed 1% joint geometric tail supplies unbounded possible scores, with NFL ties refundable and college full-game ties excluded. The tail and support gates are structural experiments, not validated improvements. All markets project the same joint score law; independent per-market temperature transformations are not used. Prior OOF residual transfer across refitted quarter models remains an assumption.

| Sport | Available input games | Games with at least score-base forecast | Refused after warmup eligibility check |
|---|---:|---:|---:|
| NCAAB | 19286 | 11983 | 1087 |
| NCAAF | 4364 | 3339 | 608 |
| NFL | 976 | 628 | 0 |

These denominators differ: initial quarters warm the model/residual archive and do not issue a scored distribution; the correction arm needs an additional prior error archive. Refusal reasons overlap and are retained in private immutable files. Source snapshots are retrospective, not independently authenticated publication vintages.

## Matched-game development results

Both arms below use exactly the same games. Lower Brier and MAE are better. Intervals are week-cluster descriptive bootstraps; prior inspection, model development and multiple comparisons prevent confirmatory interpretation.

| Sport / season label | Matched games | Score-only winner Brier | Rest/form winner Brier | Score-only / rest-form margin MAE | Score-only / rest-form total MAE |
|---|---:|---:|---:|---|---|
| NFL / 2024 | 29 | 0.28508 | 0.27307 | 12.390 / 12.475 | 10.423 / 10.645 |
| NFL / 2025 | 285 | 0.24341 | 0.25024 | 10.804 / 10.907 | 10.753 / 10.813 |
| NFL / 2026 | 121 | 0.23272 | 0.23434 | 10.272 / 10.206 | 10.977 / 11.036 |
| NCAAF / 2023 | 770 | 0.19904 | 0.19996 | 13.845 / 13.735 | 13.823 / 13.826 |
| NCAAF / 2024 | 787 | 0.21010 | 0.21297 | 14.005 / 14.041 | 13.372 / 13.367 |
| NCAAF / 2025 | 784 | 0.19762 | 0.20117 | 13.240 / 13.334 | 13.091 / 13.036 |
| NCAAF / 2026 | 485 | 0.18321 | 0.18300 | 12.513 / 12.383 | 13.610 / 13.588 |
| NCAAB / 2025 | 3607 | 0.20532 | 0.20985 | 9.331 / 9.454 | 13.826 / 13.783 |
| NCAAB / 2026 | 5841 | 0.19178 | 0.19315 | 9.893 / 9.934 | 14.672 / 14.751 |
| NCAAB / 2027 | 373 | 0.11218 | 0.11148 | 10.896 / 10.874 | 14.345 / 14.274 |

Basketball season labels follow source end-year: 2027 is the current 2026–27 season, not future results. NFL/NCAAF 2026 and NCAAB 2027 are partial seasons. The derived paired table excludes event401909694 for the existing legacy team-identity conflict; its original development row/grade is preserved in raw files. Its November3 outcome is after the frozen October1 model/residual cutoff and did not enter the current fit. Raw DEVELOPMENT_RESULTS retains the original partial-season aggregate and is not an approval-ready quarantine-filtered summary. Rest/form worsened winner scores in NFL 2025, NCAAF 2024–25 and NCAAB 2025–26. Small partial-season gains do not reverse those failures. No feature group was selected because of a favorable subset. Independent pregame Elo scores and all season-specific W/P/L, margin, total and infinite-loss results are retained in DEVELOPMENT_RESULTS.json.

Exact frozen official historical probabilities are not available for this replay; applying a November 2026 frozen fit backwards would leak future data. They remain missing. The existing official-versus-v2 prospective comparison is separately reported in ../beta-model-lab/MORNING_REPORT_20261110.md and must not be merged with this new cohort.

## Bookmaker-specific chronological replay

Existing purchased NCAA football archive was reused locally; no additional paid requests or credentials accessed. Joins require exact event/kickoff and unchanged final scores, preserve existing quarantines and use source-bound opposing prices. New probabilities are reconstructed development forecasts, never original betting probabilities. MARKET_RESULTS_VERIFIED.json supersedes the preliminary MARKET_RESULTS.json with an explicit result-score revision check.

| Season | Market | Arm | Events | Event-weighted model Brier | Event-weighted no-vig Brier | Quote-weighted hypothetical ROI |
|---|---|---|---:|---:|---:|---:|
| 2024 | moneyline | rest_form | 743 | 0.21920 | 0.18852 | -3.47% |
| 2024 | moneyline | score_base | 743 | 0.21653 | 0.18852 | -2.25% |
| 2024 | spread | rest_form | 759 | 0.28492 | 0.24921 | -6.15% |
| 2024 | spread | score_base | 759 | 0.28577 | 0.24921 | -10.20% |
| 2024 | total | rest_form | 759 | 0.25929 | 0.24961 | 6.51% |
| 2024 | total | score_base | 759 | 0.25890 | 0.24961 | 6.32% |
| 2025 | moneyline | rest_form | 731 | 0.20588 | 0.17825 | 4.37% |
| 2025 | moneyline | score_base | 731 | 0.20243 | 0.17825 | 5.61% |
| 2025 | spread | rest_form | 752 | 0.27806 | 0.24968 | -2.66% |
| 2025 | spread | score_base | 752 | 0.27553 | 0.24968 | -1.25% |
| 2025 | total | rest_form | 752 | 0.26067 | 0.25004 | -1.41% |
| 2025 | total | score_base | 752 | 0.26048 | 0.25004 | -0.70% |

Positive historical ROI cells coexist with poor probability scores and losing seasons. They are not an edge claim. The file retains push counts, selected quote counts, week-cluster paired score/ROI intervals and maximum drawdowns. One unit per selected book/line quote is a correlated diagnostic, not an executable portfolio. Independent original quote authentication and CLV remain unavailable.

NFL and NCAAB historical bookmaker-specific opposing quote archives are missing from the accessible local history store. We did not assign -110 prices, substitute consensus lines, or invent historical ROI/CLV. Their spread/total price-matched validation is blocked until a usable existing authorized archive or new prospective evidence is available.

## Prospective pilot and integrity

- NFL: {'registered': 14, 'supported': 14, 'refused': 0, 'reference_pairs': 0, 'priced_games': 0, 'settled': 0, 'outside_initial_seven_day_window_retained': 0}
- NCAAF: {'registered': 41, 'supported': 40, 'refused': 1, 'reference_pairs': 16, 'priced_games': 5, 'settled': 0, 'outside_initial_seven_day_window_retained': 5}
- NCAAB: {'registered': 511, 'supported': 441, 'refused': 70, 'reference_pairs': 189, 'priced_games': 56, 'settled': 0, 'outside_initial_seven_day_window_retained': 136}

First captures are append-only under an exclusive lock and hash-linked journal. Model/code drift stops entry. Changed teams, kickoff, neutral site or final scores append quarantines; original grades are preserved. Raw free scoreboard and summary sources are retained with capture times and hashes. Repeated reference quotes are keyed by event/book/market/line and are not independent games. Provider final results and quote scopes remain unauthenticated. NFL reference quote capture begins within48h of kickoff; its initial future games were outside that window.

Provider calendars returned adjacent-week fixtures outside the requested dates. Original farther-ahead pilot forecasts are preserved and counted separately above; the final adapter bounds new captures to seven days. They are not additional confirmation games. Frozen model feature cutoff is September30/October1 boundary UTC, the same quarterly policy used in replay. Later source refreshes do not update its roster/weather inputs. This is an intentionally recorded pilot limitation. A later model update requires a separately versioned authorized build; routine capture never fits.

Two software failures were preserved: initial replay stopped at a quarter-boundary forecast clock; first capture rejected unsupported date-range URLs with HTTP400 for all sports. The corrected single-date adapter was separately registered with byte-identical fitted models; no tuning or refit followed the capture failure. The original failed states and receipts remain.

## Preregistered confirmation design — closed

The primary endpoint is event-weighted conditional Brier difference versus a same-book no-vig comparator at a fixed pregame window, separately for3sports×3markets. Proportional no-vig is conditional on no push; W/P/L proper scores and pushes are separate mandatory endpoints. One book/window/primary side per event must be fixed before confirmation; no best-book selection after results.

A practical improvement of .005, familywise alpha .05 across nine hypotheses and80% target power are specified. All earlier games and first100 eligible prospective pilot games per sport/market are excluded. Pilot variance must be estimated by week clusters, with at least300 confirmation games and12 independent weeks as floors. Planning formula: required weeks = ceil((z(1-.05/9)+z(.80))² × variance(weekly paired mean) / .005²). This is a planning approximation; imbalance, season effects and missingness require a locked cluster-power calculation before opening. Missing NFL/NCAAB matched-price variance prevents a defensible numeric sample target today.

One final analysis at the locked sample/date; no early promotion or repeated significance testing. All refusals and coverage gaps must accompany supported-only scores. Do not open confirmation by editing a boolean or relabel this pilot. Forecast accuracy approval and executable-price profitability approval are separate. A favorable Brier test cannot itself authorize wagers.

| Sport | Moneyline | Spread | Total |
|---|---|---|---|
| NFL | NO_GO | NO_GO | NO_GO |
| NCAAF | NO_GO | NO_GO | NO_GO |
| NCAAB | NO_GO | NO_GO | NO_GO |

## Remaining work and reproduction

Acquire independently timed QB/lineup/eligibility, workload and weather evidence before those features can enter a registered numeric experiment. NFL/NCAAB need historical paired price evidence; all three need original source-time and legal execution evidence. Keep the failed rest/form result; the next feature group needs a separate protocol and development version. No unlimited feature search is authorized by the scheduled runner.

Active state: `/Users/wadeholland/Documents/Codex/Project-Craps/state/research-extensions/three-sport-development-20261110-r5`. `python -m research.three_sport_validation shadow --state STATE --output UNIQUE_RECEIPT.json` verifies and captures/grades without fitting. `python -m research.three_sport_validation_report --state STATE --output OUTPUT` reproduces this report without fitting. Source inputs, models and protocols are hash-pinned; build/register are initial development commands and are never routine. Exact source paths/hashes are in SOURCE_MANIFEST.json; exact branch/commit in COMMIT_RECEIPT.json.

46 targeted regression tests passed, covering future-result exclusion, quarter-boundary clocks, sign conventions, complementary prices, pushes, NFL tie scope, monotone lines, impossible college ties, first-capture idempotence, impossible future finals, independent Elo embargo and journal tampering, plus existing calibration/market tests. The final capture adapter amendment preserved the earlier fitted models and original pilot files byte-for-byte in a new registered state; it did not refit or retune.

For any eventual real wager: independent validation and explicit production authorization, complete current pregame inputs, a fresh executable exact event/book/market/selection/line/price, qualification and configured fractional-Kelly sizing with risk caps. Hard Rock requires Florida identity; DraftKings remains reference-only. Official baseline13–8, estimated bankroll$7,705.48 and$400unit unchanged.

## New pregame official and Elo comparison cohort

A separately registered, no-fit comparator entry now executes the frozen official coefficients on date-aware available history and recomputes both challenger arms at the new comparison issuance time. It stores an independent fixed K20/HFA55 winner Elo. These are new pregame research references, not restored original betting probabilities. The original first forecasts remain untouched. Official NCAAB logistic winner probabilities remain distinct from official score-kernel winner probabilities; NFL/NCAAF use their official score distributions. Inputs remain retrospective/source-time unauthenticated, and old challenger feature cutoffs remain explicit.

- NFL: {'games': 14, 'independent_elo_games': 14, 'official_score_reference_games': 14, 'exact_official_logistic_winner_games': 0, 'reference_pairs': 0, 'official_refusals': {}}
- NCAAF: {'games': 40, 'independent_elo_games': 40, 'official_score_reference_games': 40, 'exact_official_logistic_winner_games': 0, 'reference_pairs': 16, 'official_refusals': {}}
- NCAAB: {'games': 439, 'independent_elo_games': 439, 'official_score_reference_games': 439, 'exact_official_logistic_winner_games': 439, 'reference_pairs': 189, 'official_refusals': {}}

Later first book/line captures append new comparison vintages at their actual current issuance time. Repeated vintages are not independent games. The initial college comparator call failed on a missing explicit refund argument; its failed receipt is preserved, corrected code separately registered, with no refit. Missing official D1 schedule matches are refusals, not replaced by inferred probabilities. Explicit official/provider identity or kickoff conflicts append persistent quarantines (currently401928789 and401922239); their original records remain, and paired summaries exclude them. Routine comparator mode cannot register itself if registration is missing.

Reproduce: `python -m research.three_sport_comparators --state STATE --output UNIQUE_RECEIPT.json` without --register.
