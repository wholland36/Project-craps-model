# Project Craps — NFL, NCAA Football, NCAA Basketball validation gate

**All three models remain RESEARCH ONLY.** A successful historical score backtest or
a GitHub Actions green check must never be labeled a verified betting advantage.

This branch extends the existing comprehensive Football research/Sheets baseline
with the men's NCAA basketball score research engine and a common independent
historical sportsbook-price audit. It does **not** invent unavailable sportsbook
opening/closing prices, retrospective injury reports, real orders, or probability
estimates. Research reports and market audit stay separate from the user's private
canonical Google Sheet. Existing official wagers are never modified.

## Supported model scope and current state

| Sport | Historical score model | Causal rest/Elo | Paired exact sportsbook quote dataset | Verified production edge |
| --- | --- | --- | --- | --- |
| NFL | existing NFL runner and challengers | yes | incomplete, original quote clocks unknown | no |
| NCAAF FBS | existing FBS runner and challengers | yes | unavailable verified same-book paired lines | no |
| NCAA men's basketball | `models/train_ncaab.py`, 2016-2025 seasons | yes, research baseline | unavailable verified same-book paired lines | no |

NCAA women's basketball, NBA, WNBA, NHL, soccer, MLB and other sports are **not
included** in these particular three-sport models. Each requires a separate
source, model, and holdout calibration. Avoid passing another sport to an approved
football or men's-college-basketball model.

## Runnable tools

Install `pip install -r requirements-research.txt`, then:

```sh
python -m unittest discover -s tests -v
python -m models.train_ncaab --output runtime/ncaab-research-UNIQUE.json
python -m research.market_audit --input runtime/private-original-market-quotes.jsonl --output runtime/market-audit-UNIQUE.json
```

The historical market audit requires one **verified original per-market offer**
and a **paired opposing-side price from the same sportsbook and exact same
timestamped line**, frozen market-blind prediction and full-game official final.
Each JSONL row must have a unique `event_id`, explicit sport and season,
event kickoff and quote/model UTC timestamps, book, side, selected-side handicap,
the two original American odds, opposing_book, opposing_quote_time_utc and opposing_line (the opposite signed handicap for spreads, the identical threshold for totals), three-way `p_win`, `p_push`, `p_loss`, actual
home/away points, source URLs and separate source-content SHA-256 hashes.
`market_pair_verified` is required, but self-attestation alone is **not independent
source authentication**; quote evidence must be audited externally before
any production review.

Spread `line` is the selected side's signed handicap, not the favorite's
unsigned number. Total `line` is the posted full-game total; positive EV
uses actual price and push-aware 3-way outcomes. Moneylines use the listed
home/away selection, full-game including overtime only, with ties refunded
in NFL. Market no-vig comparison is conditional on non-push on identical
quote lines; it is not a fair-line substitute.

The audit computes per-season paired Brier scores, synthetic fixed-rule
selection counts/ROI, event-cluster bootstrap intervals and exact data coverage.
The exact pre-specified research screen is spread >= 2.5pp adjusted
conditional non-push edge, total >= 3pp, moneyline >=3pp. There is no
optimized threshold fitted to holdout winners. **Selected rows are purely
hypothetical**; no official ticket is created and no $400 bet is approved.

## Missing before genuine production release

1. Independently audit market quote/source timestamps and complete game/market
   coverage, identify favorite-orientation and line/price mismatches; historical
   datasets with no original clock must remain unverified.
2. Add NCAA basketball D-I venue-neutral flags and actual neutral-site priors,
   roster and transfer player availability/vintages, projected minutes, possessions,
   opponent-adjusted efficiency and strength of schedule.
3. Securely ingest pregame sportsbook executable quotes, as-of injuries/QBs/weather
   for NFL/FBS and roster/lineups for NCAA basketball. Exact capture clocks required.
4. Bind independent frozen model artifacts (NFL, FBS, men's NCAA basketball) to
   the shared append-only pregame registry. Reconcile/cite canonical Sheets
   *read-before-write*, and read back every forecast. The existing football
   pipeline's Sheets outbox is **not** yet extended to NCAAB.
5. Compare challenger to strong time-matched market no-vig/Elo baselines over
   untouched seasons and prospective cohorts. Evaluate moneyline, spreads,
   totals, pushes, selection uncertainty, calibration and drawdown on all
   available markets rather than cherry-picked winners.
6. Only after independent coverage, calibration, calibration confidence and
   positive holdout evidence may an explicitly reviewed release manifest
   promote a model. No automated promotion or placing bets.

Never put private historical tickets, access tokens, screenshots or
credentials in public GitHub or CI logs.

## Provenance and reproducibility

Causal feature histories are pregame-only with date-isolated updates.
Historical source publication clocks are generally unknown, so retrospective
features may have information-vintage limitations. The exact downloaded
sportsdataverse NCAA basketball historical season files are the referenced
source; the model report identifies the seasons and data URL template.
The original NFL/FBS source manifests are retained under the existing
football research pipelines. Market audit includes SHA-256 of its complete
input, immutable event quote keys, rejected records and reason codes.

## New: optional real timestamped odds capture

Provider research confirms The Odds API offers historical American NFL, NCAA
football and NCAA men's basketball sportsbook snapshots from 2020 onward; this
**requires a paid plan**. A key is not present, and NO authenticated historical
prices were fetched in this development run. Do not publish or commit the key.

```sh
export THE_ODDS_API_KEY='KEY_FROM_PRIVATE_PASSWORD_MANAGER'
python -m research.odds_api_ingest --sport NFL --mode historical --at 2025-10-21T18:00:00Z --output-dir runtime/odds-NFL-unique
python -m research.odds_api_ingest --sport NCAAF --mode historical --at 2025-10-21T18:00:00Z --output-dir runtime/odds-FBS-unique
python -m research.odds_api_ingest --sport NCAAB --mode historical --at 2025-11-10T18:00:00Z --output-dir runtime/odds-MBB-unique
```

For current offers, use `--mode live` (without `--at`).
The code validates paired opposing prices and aligned signed handicaps at a single
book and market clock; retains source JSON bytes and SHA-256 in a **private runtime
folder**; excludes odds after the published game start and malformed quarter
lines. Never mix book identities or inferred timestamps. It produces **quote
observations only**, not actual model forecasts or validated expected values.
The private normalized quotes must be linked to immutable model forecasts and
settled outcomes *without postgame leakage* before running the market audit.
Current bookmaker eligibility and coverage must be established separately.
