# Executable readiness — November 3, 2026

**Research-only, NOT a validated production wagering model.**

This branch adds a standalone pregame forecast/quote engine with real three-way push-aware EV, conditional nonpush edge, fail-closed validation gates and immutable append-only JSONL snapshots. No paper or live bets are automatically placed.

The original NFL Ridge/rolling historical benchmark and NCAA benchmark are **research only**: historical quote timestamps, same-book executable data, feature provenance, injury/QB and weather revisions, model release gates, multi-season held-out profit uncertainty and 2026 recalibration remain incomplete. A green CI job does not prove a positive betting edge.

To execute an explicitly supplied fixture: `python -m models.run_pregame --input fixtures.json --output results/forecasts.jsonl`. Input is a JSON object with `bankroll` and nonempty `quotes`; each quote has event_id, start/observed UTC, book, sport, market, selection, line, american_odds and executable_verified. Optional per-quote distribution fields: win, push, loss, asof_utc, model_version, provenance. Optional release manifest must pass **all** declared validation gates; absent manifest gives zero approved risk.

**No private wager spreadsheets or sportsbook credentials** are copied into the public repository. Google Sheets remains authoritative for Official Wagers, Dashboard, Forecast Registry and Research Outcomes. JSONL is a local research artifact and is not represented as synchronized Sheets persistence.

Immediate production blockers: reproducibly versioned forward-chaining model artifacts for each sport; chronological pregame roster/weather/opponent-adjusted feature sets; timestamped same-book prices; independent Elo and same-event no-vig baseline comparisons; robust multi-season probability/ROI calibration with push-aware payoffs and uncertainty; live scheduler/data ingestion; secure, read-before-write Google Sheets append/dedupe with verification. Until then only NOT_COMPUTED/CANDIDATE/PASS and $0 approved risk are appropriate for live selections.
