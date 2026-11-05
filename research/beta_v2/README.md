# Beta v2 research runtime

Separate NFL/NCAAB immutable research experiment; official defaults and v1 stay frozen.

Run with the workspace validation Python: `python -m research.beta_v2.runtime --output ABSOLUTE_OUTPUT`. Add `--prepare` once daily at 06:00 Eastern to create a fresh immutable fitted bundle under the fixed algorithm. Normal runs must collect context. Never change the frozen algorithm manifest to bypass drift.

`training` and `strength`: source/box joins, parsed UTC clocks, reconstructed 24-hour historical result lag, rolling-origin OOF and season-shrunk current strength. NFL is a full-score fallback, not drive efficiency. Basketball has regulation-normalized pace and explicit empirical OT-duration correction, not a validated game-specific overtime process.

`calibration`: regularized joint margin-total tilt bound to exact parent hash; coherent market projections, explicit category support and infinite-logloss failures. Historical development results are inspected development, not independent confirmation.

`benchmarks`: read-only canonical hash verification, exact official basketball logistic winner and separately labeled score-kernel/independent Elo. Official original forecast records are never filled or rewritten.

`context` and `markets`: candidate free source collection, typed verified role/feature/quote inboxes, original byte hash/effective-time checks, replacement capacity guards and exact same-book paired prices. Numerical injury application is optional mean-only and requires independently identified comparator-bound values; none fitted at launch. A captured feed is not independent source authentication.

`protocol` and `runtime`: separate day-ahead/early/final immutable keys, per-date immutable fits, append-only settlements, exact identity revisions quarantined, conditional/win-push-loss proper scoring, descriptive daily monitoring, pilot exclusion and future confirmation gates. No automatic betting approval.

Review-item implementation statuses explicitly mark unavailable data, unfinished extensions and future evidence. Do not describe the infrastructure as having completed every proposed statistical study.
