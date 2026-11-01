# Project Craps football research pipeline

Runnable NFL regular-season and NCAA FBS-vs-FBS research, with frozen model artifacts,
market-blind inference, push-aware prices, an append-only forecast registry and a
restricted Google Sheets outbox. NCAA basketball is not supported.

**Every forecast is PASS for wagering and has approved risk $0.** This implementation
cannot place bets, approve a model, change an official ticket or backfill an original
probability. `VALIDATION_RULES.md` remains the release policy. Research version
`football-paired-residual-v1-research` is a new challenger, not recovered Model 2.1.

## Install and test

Use Python 3.11 or 3.12 in production/CI. Python 3.9 also works locally.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
```

Run the following commands from the repository root with the environment active.
All output directories are new, exclusive-create locations. Reuse the same private
registry across runs; use a new directory name for each source capture/model build.
`runtime/`, credentials and private ledger files are ignored by Git.

## Capture and build both models

```sh
python -m project_craps capture --sport NFL --start-year 2010 --end-year 2026 --output runtime/capture-NFL-001
python -m project_craps capture --sport NCAAF --start-year 2016 --end-year 2026 --output runtime/capture-NCAAF-001
python -m project_craps train --snapshot runtime/capture-NFL-001/snapshot.json --output runtime/models/NFL
python -m project_craps train --snapshot runtime/capture-NCAAF-001/snapshot.json --output runtime/models/NCAAF
```

The default train split uses seasons through 2023, validation residuals from 2024,
and untouched 2025 evaluation. Separate 2022-2025 folds fit through test year minus
two, calibrate on the previous season and evaluate the next. Hyperparameters and
synthetic diagnostics are fixed in code. Current-season outcomes never enter these
fits. Rebuilding is explicit; no workflow promotes a model.

Each capture saves exact public source bytes with SHA-256, URL and actual observation
time. NFL uses nflverse's regular-season schedules/scores; NCAA uses cfbfastR's FBS
schedules, retaining provider game and team IDs. Loading verifies both the raw hash
and reconstruction of normalized rows. Paid data is never requested or retried.

Historical publication timestamps are unavailable. Historical features batch by UTC
kickoff date to avoid same-day updates, but this is retrospective research, not proof
of point-in-time historical availability. Live state only reads completed games
observed before issuance. Models include frozen coefficients, feature order, paired
validation residuals, true split cutoffs, exported state, source manifest and a code
fingerprint. Inference refuses a changed implementation; build a new challenger
explicitly after code changes. Preserve the previous artifact and registered records.

The scores model uses rolling points for/against, independently computed Elo, games
played, rest and neutral venue. It does not estimate numerical QB/injury or weather
adjustments. Those limitations prevent wagering approval. State includes later
completed holdout games for future inference; those results never refit coefficients
or validation residuals. Live inference reconstructs state from a fresh full history,
starting at exactly the same season as the fitted features.

## Probability and quote contracts

Independent margin/total means use no odds inputs. Paired validation residuals produce
joint home/away scores, rounded to feasible nonnegative integers. NCAA full-game
support is conditioned on a non-tie because overtime must resolve the game. This
is an experimental distribution assumption that needs prospective calibration.

Only after that distribution is frozen does the quote enter W/P/L classification:

- Moneyline: `selection` is `home` or `away`; `line` is null and `tie_policy` must be
  `refund`. Full-game NFL ties refund under this supported contract. Three-way and
  regulation-only markets are rejected.
- Spread: `selection` is `home` or `away`; `line` is that selected team's handicap.
  Home -3 means home margin minus three must be positive. No moneyline inference
  determines the spread sign. nflverse's signed home-margin spread is the negative
  of this home-handicap convention; do not pass it through unchanged.
- Total: `selection` is `over` or `under`; `line` is the total. Only integer and
  half-point lines are supported.

EV per unit risk is `P(win) * net payout - P(loss)`. Pushes refund risk. Fair odds
and price break-even use probabilities conditional on non-push. The registry keeps
all three unconditional masses and labels their definitions.

A quote JSON file has this shape (illustrative placeholders, not executable offers):

```json
{
  "sport": "NFL", "event_id": "PROVIDER_GAME_ID",
  "home_id": "HOME_ID", "away_id": "AWAY_ID",
  "kickoff": "2030-11-03T18:00:00+00:00",
  "book": "OBSERVED_BOOK_ID", "source_url": "https://provider.example/quote",
  "scope": "full_game_including_overtime", "market": "spread",
  "selection": "home", "line": -3, "american_odds": -110,
  "observed_at": "2030-11-03T17:58:00+00:00",
  "expires_at": "2030-11-03T17:59:00+00:00",
  "verified_executable": false
}
```

Context is a JSON object keyed by `quarterback`, `roster`, and `weather`. Each item
requires the matching `sport` and `event_id`, `status: "RESOLVED"`, actual
`observed_at`, a source URL and notes explaining the observation. These are operator
observations, not fabricated model adjustments. Do not mark unresolved injuries or
uncertain starters RESOLVED. A model cannot establish the truth of a supplied note.

Sources/schedule must be observed within 12 hours, context within six hours and the
quote within five minutes. All observations must precede issuance. A matching future
kickoff, unexpired quote, confirmed start time and at least eight observed games per
team are required. Missing inputs persist a BLOCKED research record with p and EV
NOT_COMPUTED. Integrity failures or a started event abort instead of appending.
Complete inputs produce EXPERIMENTAL p/EV with qualification PASS and zero risk.
These fixed freshness defaults are conservative engineering limits, not validated
betting rules; uncertainty remains NOT_VALIDATED even with complete context.

```sh
python -m project_craps forecast --model runtime/models/NFL/model.json --snapshot runtime/capture-NFL-001/snapshot.json --event-id PROVIDER_GAME_ID --quote runtime/quote.json --context runtime/context.json --registry runtime/forecast_registry.sqlite
python -m project_craps verify --registry runtime/forecast_registry.sqlite
```

Omit quote/context to exercise the real missing-input PASS path. There is no CLI
backdating option. Only the current system clock can issue/register a forecast.

## Daily runs and research settlement

```sh
python -m project_craps daily --models runtime/models --output runtime/daily-UNIQUE-RUN-ID --registry runtime/forecast_registry.sqlite
```

Daily captures both sports, processes only today's Eastern-date unstarted events,
preserves the first forecast and writes per-sport status plus a registry anchor.
One sport's failure does not stop the other; the command exits nonzero on failure.
Optional `--quotes` and `--context` files map `SPORT:PROVIDER_GAME_ID` to observations.
Without them every screen is a zero-risk PASS. Optional `--sync` invokes the
credentialed restricted writer after local persistence. There is no forced play.

After a fresh final-score capture:

```sh
python -m project_craps settle-research --registry runtime/forecast_registry.sqlite --snapshot runtime/capture-NFL-AFTER/snapshot.json
```

Settlement requires the exact registered event identity/kickoff and a source
observation after kickoff. It grades only the original registered probability.
BLOCKED records are never added to the calibration sample. Changed results, teams
or kickoff are quarantined by rejection and need separate review; the original is
preserved. These are local research results, never official tickets or official P&L.
Revisions and multiple markets on one event remain correlated observations.

## Canonical Google Sheets integration

Copy `config/ledger.example.json` to ignored `runtime/ledger.json` and bind the
verified canonical spreadsheet ID, Forecast Registry sheet ID and Official Wagers
sheet ID. Set `PROJECT_CRAPS_LEDGER_CONFIG` to use another private config path.
The private binding and official ticket data must never be committed.

Two supported delivery routes use the same projection, schema checks and readback:

1. Background REST: install `requirements-google.txt`; configure Google Application
   Default Credentials outside the repository and grant the identity access to the
   canonical Sheet. Run `python -m project_craps sync --registry runtime/forecast_registry.sqlite`.
   Do not put service-account keys, access tokens or official wager history in GitHub
   secrets/artifacts unless a separate reviewed deployment explicitly requires them.
2. Connected-tool delivery: the agent reads native metadata and bounded cell values,
   records an ignored remote snapshot, then runs `prepare-sync`. It sends only the
   returned `requests` through the connected Google Sheets tool, re-reads both tabs,
   and runs `ack-sync` using the readback. This route was exercised during implementation.

Remote snapshots have `spreadsheet_id`, `registry_sheet_id`, `registry_title`,
`official_sheet_id`, `rows` (header plus data), `official_rows`, `column_formats`
(from the last literal exemplar), and `writable_schema_safe: true` only after
confirming there are no formulas, chips or data validation in the append schema.
The background transport performs that inspection itself. The writer copies the
exemplar formats and writes literal values, never formulas. A future structured
schema is rejected pending an explicit adapter change.

```sh
python -m project_craps prepare-sync --registry runtime/forecast_registry.sqlite --remote runtime/remote-before.json --output runtime/prepared-UNIQUE.json
python -m project_craps ack-sync --registry runtime/forecast_registry.sqlite --remote runtime/remote-after.json --prepared runtime/prepared-UNIQUE.json --output runtime/readback-UNIQUE.json
```

The writer only appends to the configured Forecast Registry. It cannot send an
Official Wagers update. It verifies exact headers, detects conflicting/duplicate
forecast IDs, appends pending rows, re-reads every payload and compares Official
Wagers before/after before acknowledging delivery. An uncertain response leaves
records pending; the next run reconciles IDs/content before deciding to append.
Probability, push mass, provenance hashes and first-forecast links are retained in
the notes JSON. The historical EV-per-$400 column is hypothetical research sizing;
Kelly and approved risk stay zero. Thresholds remain NOT_COMPUTED.

Use one shared registry and writer. SQLite serializes local forecast transactions;
a process lock serializes delivery. Google Sheets provides no cross-client unique
constraint, so independent machines must not deliver the same PCR IDs concurrently.
Manual connected-tool prepare/write/readback must be serialized as one operation.

SQL triggers reject forecast/result/receipt UPDATE or DELETE; the forecast hash
chain detects payload changes and missing/reordered interior rows. Preserve anchors
outside the database, and use `verify --anchor PATH` to detect truncation against
that checkpoint. A database owner can bypass triggers or replace the entire file;
local append-only storage is not a substitute for an external immutable backup.

## Validation and deployment limits

Current evaluation includes home-win Brier/log loss, home-rate and independent Elo
baselines, calibration buckets, season-by-season folds, three-way synthetic-line
scores and non-push conditional diagnostics. Paired week-cluster bootstrap intervals
are descriptive and do not approve a model. Strong bookmaker comparisons, betting
ROI, drawdown and CLV stay NOT_COMPUTED without authenticated timestamped book/price
history. Synthetic thresholds are not sportsbook simulations.

Tests cover both sports, market perturbation, integer/half-point pushes, explicit tie
rules, future/stale/mismatched inputs, same-day update isolation, future-result
training isolation, concurrent/idempotent registry appends, immutability/corruption,
research settlement, schema drift and ambiguous Sheets-write recovery.

CI tests Python 3.11/3.12 on PRs. Separate historical workflows capture and train each
sport, run the tests and upload complete versioned research artifacts on success.
No production schedule, credentials, automatic model promotion or wager placement
is enabled by these workflows. An existing daily agent can invoke the documented
`daily` command. Background scheduling still needs a persistent registry location,
verified authentication and an operator-owned deployment; a throwaway CI checkout
must not become the canonical first-forecast store.

Archived pre-audit programs under `legacy/` are comparison evidence with known bugs.
Current workflows never execute them. The new reports supersede their arithmetic
for research; they do not alter any original forecast or official wager record.
