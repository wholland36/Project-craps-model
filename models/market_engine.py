"""Project Craps: push-aware payoff/qualification with fail-closed production gates.

No fitted probabilities are invented here. A validated upstream model must provide
a three-way probability distribution and a separately approved release manifest.
No personal wager data or bookmaker credentials belong in this repository.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from hashlib import sha256
import json
import math

THRESHOLDS = {"spread": 0.025, "total": 0.030, "moneyline": 0.030}
REQUIRED_RELEASE_CHECKS = (
    "chronological_holdout", "same_event_market_baseline",
    "independent_elo_baseline", "three_way_push_calibration",
    "same_book_timestamped_prices", "roi_uncertainty",
    "approved_production_model"
)

@dataclass(frozen=True)
class Quote:
    event_id: str
    event_start_utc: str
    observed_utc: str
    book: str
    sport: str
    market: str
    selection: str
    line: str
    american_odds: int
    executable_verified: bool = False

@dataclass(frozen=True)
class Distribution:
    win: float
    push: float
    loss: float
    asof_utc: str
    model_version: str
    provenance: str

def parse_time(s: str) -> datetime:
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if d.tzinfo is None:
        raise ValueError("timestamp must be timezone aware")
    return d.astimezone(timezone.utc)

def payout(american: int) -> float:
    if not american or -100 < american < 100:
        raise ValueError("invalid American odds")
    return american / 100 if american > 0 else 100 / -american

def breakeven(american: int) -> float:
    return 1 / (1 + payout(american))

def three_way_ev(dist: Distribution, american: int) -> float:
    """Return net EV as fraction of risk; a push refunds the stake."""
    return dist.win * payout(american) - dist.loss

def qualify(quote: Quote, dist: Distribution | None, release: dict | None,
            bankroll: float, max_stake: float = 400.0) -> dict:
    if quote.market not in THRESHOLDS:
        raise ValueError("unsupported market")
    if bankroll < 0 or max_stake < 0:
        raise ValueError("negative bankroll/stake")
    start, observed = parse_time(quote.event_start_utc), parse_time(quote.observed_utc)
    if observed >= start:
        raise ValueError("quote not pregame")
    result = {"quote": asdict(quote), "state": "CANDIDATE", "approved_risk_usd": 0,
              "official_placed": False, "model_probability": "NOT_COMPUTED",
              "fair_line": "NOT_COMPUTED", "ev_per_dollar": "NOT_COMPUTED",
              "stake_cutoff": "NOT_COMPUTED", "blockers": []}
    result["break_even_conditional_nonpush"] = round(breakeven(quote.american_odds), 9)
    if not quote.executable_verified:
        result["blockers"].append("No directly verified executable same-book offer")
    if dist is None:
        result["blockers"].append("No independent exact pregame model distribution")
    else:
        forecast_time = parse_time(dist.asof_utc)
        if forecast_time >= start:
            result["blockers"].append("Model forecast was not frozen before event start")
        probs = (dist.win, dist.push, dist.loss)
        if any(not math.isfinite(p) or p < 0 or p > 1 for p in probs) or not math.isclose(sum(probs), 1, abs_tol=1e-8):
            raise ValueError("three-way probabilities must be valid and sum to 1")
        if not dist.provenance or not dist.model_version:
            result["blockers"].append("Missing model version or reproducible provenance")
        result["model_probability"] = {"win": dist.win, "push": dist.push, "loss": dist.loss}
        result["ev_per_dollar"] = round(three_way_ev(dist, quote.american_odds), 9)
        # Conditional non-push edge is distinct from stake EV, which includes push.
        if 1 - dist.push <= 0:
            result["blockers"].append("All probability mass is push")
        else:
            conditional_win = dist.win / (1 - dist.push)
            result["adjusted_edge_conditional_nonpush"] = round(
                conditional_win - breakeven(quote.american_odds), 9)
            if conditional_win - breakeven(quote.american_odds) < THRESHOLDS[quote.market]:
                result["blockers"].append("Adjusted edge below sport-market threshold")
            if three_way_ev(dist, quote.american_odds) <= 0:
                result["blockers"].append("Non-positive three-way EV")
    release = release or {}
    if not release.get("release_id") or not release.get("sport") == quote.sport:
        result["blockers"].append("No matching model release manifest")
    for check in REQUIRED_RELEASE_CHECKS:
        if release.get(check) is not True:
            result["blockers"].append("Release gate not verified: " + check)
    if not result["blockers"] and dist is not None:
        # Conservative quarter Kelly with push refund and a 1-unit maximum.
        edge_ev = three_way_ev(dist, quote.american_odds)
        b = payout(quote.american_odds)
        kelly = max(0.0, edge_ev / (b * (dist.win + dist.loss)))
        size = min(bankroll * kelly * 0.25, max_stake)
        if size > 0:
            result["state"] = "VALIDATED QUALIFYING BET"
            result["approved_risk_usd"] = round(size, 2)
    return result

def snapshot_id(quote: Quote, forecast_asof_utc: str) -> str:
    fields = [quote.event_id, quote.market, quote.selection, quote.line,
              quote.book, quote.observed_utc, forecast_asof_utc]
    return sha256(json.dumps(fields, separators=(",", ":")).encode()).hexdigest()[:24]

def new_record(quote: Quote, dist: Distribution | None, release: dict | None,
               bankroll: float) -> dict:
    result = qualify(quote, dist, release, bankroll)
    asof = dist.asof_utc if dist else quote.observed_utc
    result.update({"snapshot_id": snapshot_id(quote, asof),
                   "snapshot_asof_utc": asof, "model_version": dist.model_version if dist else "2.1-NOT_COMPUTED",
                   "model_provenance": dist.provenance if dist else "UNAVAILABLE"})
    return result
