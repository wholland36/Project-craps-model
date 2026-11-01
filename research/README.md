# Controlled football model improvement

This module adds failure analysis, opponent-adjusted scoring, prior-game efficiency,
discrete distribution comparisons and private prospective tracking. It leaves the
frozen `project_craps` runner and official wager history unchanged. No experiment
can approve a model or a stake.

## Registered design

`protocol.json` fixes five ablations and their parameters: original, scaled inputs,
opponent-adjusted scoring, efficiency inputs, and a score-kernel mixture. Each
2022-2025 fold trains through year minus two, calibrates on year minus one and tests
the next season. The scaler fits only on training rows. Each fold exports all
coefficients, validation residuals, score support, feature order and hashes.

These historical seasons were examined in earlier audits. This is a retrospective
comparison, not a fresh untouched test. Paired ISO-week bootstrap intervals are
descriptive and not adjusted for multiple comparisons. No model is automatically
selected or promoted, including after a favorable retrospective result.

NFL efficiency comes from public nflverse team-game statistics: EPA per estimated
scrimmage play, play volume, lost turnovers per play, sacks per dropback, and
explosive passes/rushes. Explicit provider aliases align OAK/LV, SD/LAC and STL/LA
statistics within the same provider game ID. The frozen baseline's team-state
semantics remain unchanged for the controlled comparison.

FBS EPA, volume, turnovers and explosive rates use cumulative weekly summaries.
A summary is eligible only after the associated regular-season week's latest
scheduled kickoff plus a conservative 48-hour lag, and before the target game.
For a future observation it must also precede the actual as-of cutoff. These lags
avoid obvious within-week lookahead; they do not prove historical publication time.
Only raw metric columns are used, never retrospectively published rankings.

Actual FBS sacks come from separately archived attributed player-play records,
deduplicated by provider event/play/team. Havoc is not mislabeled as sacks.
Opponent EPA adjustments use only earlier information about opponents faced.
Missing metrics use named fixed priors and explicit coverage flags. The volume
feature is plays per game, not measured seconds between snaps.

Returning-production and transfer-portal sources are archived and indexed. They
are not silently inserted into historical training because their original
publication and roster-effective timestamps are unavailable. Current injuries,
rosters, weather and raw provider prices are captured separately for future work.
No numerical injury/weather adjustment or executable quote is invented.

## Commands

Install from the repository root:

```sh
.venv/bin/python -m pip install -r requirements-research.txt
.venv/bin/python -m unittest discover -s tests -v
```

Capture public sources once into a new directory:

```sh
.venv/bin/python -m research.ingest --sport NFL --start-year 2010 --end-year 2026 --output runtime/research-input-NFL-UNIQUE
.venv/bin/python -m research.ingest --sport NCAAF --start-year 2016 --end-year 2026 --output runtime/research-input-FBS-UNIQUE
```

The FBS capture also saves returning-production, portal and attributed-play files.
Capture errors are not retried. Each response has its own hash and actual
observation receipt. The original publication timestamp remains null if unknown.
Use the existing `project_craps capture` command for schedules. Keep all runtime
files private and out of Git.

Register the unchanged protocol before fitting:

```sh
.venv/bin/python - <<'PY'
from project_craps.common import create,envelope,read,stamp,now
create('runtime/research-protocol-UNIQUE.json', envelope({
    'registered_at':stamp(now()), 'protocol':read('research/protocol.json')}))
PY
```

Run comparisons on saved, verified source bytes:

```sh
.venv/bin/python -m research experiment --snapshot runtime/nfl-capture/snapshot.json --metrics runtime/improvement-data/NFL/manifest.json --protocol-registration runtime/improvement-protocol-registered.json --output runtime/research-results-NFL-UNIQUE
.venv/bin/python -m research experiment --snapshot runtime/ncaaf-capture/snapshot.json --metrics runtime/improvement-data/NCAAF/manifest.json --player-metrics runtime/improvement-data/NCAAF-player-plays/manifest.json --protocol-registration runtime/improvement-protocol-registered.json --output runtime/research-results-FBS-UNIQUE
```

Failure reports separate model-implied favorite/margin/total groups from unverified
book-line groups. FBS book-line groups stay UNKNOWN when no line source exists.
Key margins of three/seven, ties, high-total tails and every registered integer/
half-point threshold have predicted/observed diagnostics. Non-push scores condition
on non-push, while W/P/L scores retain all three outcomes.

```sh
.venv/bin/python -m research.analysis.failure --results runtime/improvement-final/NFL --output runtime/NFL-failure-UNIQUE.json
.venv/bin/python -m research.analysis.failure --results runtime/improvement-final/NCAAF --player-metrics runtime/improvement-data/NCAAF-player-plays/manifest.json --output runtime/FBS-failure-UNIQUE.json
.venv/bin/python -m research.analysis.benchmarks --results runtime/improvement-final/NFL --snapshot runtime/nfl-capture/snapshot.json --output runtime/NFL-benchmark-UNIQUE.json
```

The NFL benchmark is the source-snapshot no-vig moneyline; FBS uses source-reported
pregame Elo. Both lack authenticated original publication evidence and are labeled
post-fit descriptive diagnostics. Actual ties are excluded and model probabilities
conditioned consistently for that comparison. These are not ROI/CLV simulations.

## Prospective shadow cohorts

```sh
.venv/bin/python -m research observe --snapshot runtime/nfl-capture/snapshot.json --metrics runtime/improvement-data/NFL/manifest.json --models runtime/improvement-final/NFL --registry runtime/football-shadow.sqlite --output runtime/shadow-NFL-UNIQUE --days 7 --max-events 20
.venv/bin/python -m research observe --snapshot runtime/ncaaf-capture/snapshot.json --metrics runtime/improvement-data/NCAAF/manifest.json --player-metrics runtime/improvement-data/NCAAF-player-plays/manifest.json --models runtime/improvement-final/NCAAF --registry runtime/football-shadow.sqlite --output runtime/shadow-FBS-UNIQUE --days 7 --max-events 20
```

This registers private unadjusted shadow predictions for the same fixed candidates
before kickoff. They are not released as validated betting probabilities or written
to the canonical wager/forecast ledger. All carry zero approved risk and disclose
missing confirmed QB/OL/roster, numerical context adjustments and executable quotes.
All variants are retained, so no retrospective winner is selectively tracked.

Only exact future provider event identities are accepted. Summary sources confirm
kickoff, team and pregame status; actual mismatches are quarantined. Explicit
LAR/LA and WSH/WAS provider aliases are supported. Retrieval failures remain explicit
missing context. Raw observations preserve their actual retrieval times and hashes.

The shadow store preserves first event records and revisions under a registered
protocol, rejects UPDATE/DELETE, verifies a hash chain and serializes processes
with a file lock and a full-synchronous rollback journal. It preserves the original
error on an uncertain commit; retries reconcile the existing key without rewriting
issuance time. A database owner can bypass local guards, so save external anchors.
Private shadow records are research data, not a second official wager ledger.

After a fresh final-result capture:

```sh
.venv/bin/python -m research settle --snapshot runtime/NEW-FINAL-SNAPSHOT/snapshot.json --registry runtime/football-shadow.sqlite
.venv/bin/python -m research.analysis.forward --registry runtime/football-shadow.sqlite --output runtime/forward-report-UNIQUE.json
```

Settlement requires the original source observation to follow kickoff. It cannot
relabel an earlier capture as a postgame result, change a prior result or backfill
a missing original probability. Forward reports count only first event records,
not revisions or alternative model probabilities as independent games. A small
forward cohort cannot establish profitability or approve a stake.

`research.analysis.observations` indexes archived raw weather/price/roster payloads
and annual data availability. It does not turn provider prices into Hard Rock
execution offers or infer a starting QB from the absence of an injury tag.

## Execution and release

The manual `Football challenger research` Actions workflow reproduces both sport
experiments on public historical data. PR tests run Python 3.11 and 3.12. The
historical NFL/FBS workflows install the research test dependencies too. No live
shadow probabilities, private target bindings or official wagers go into public
Actions artifacts. No new recurring schedule or automatic model promotion is added.

The implementation run found a promising FBS improvement and no demonstrated NFL
improvement. Full denominators and uncertainty are in the saved reports. Favorable
historical metrics still require timestamped future evidence, strong benchmarks,
material roster/weather handling and risk-adjusted quote-level validation under
`VALIDATION_RULES.md` before any wagering approval.
