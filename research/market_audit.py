"""Strict three-sport, *historical* bookmaker-quote validation audit.

Reads private caller-provided JSONL forecast+quote observations, never imports
historical wager ledger. Results are research diagnostics, NOT live signals.
Requires same-book paired opposing quotes and original pregame timestamps.
Missing inputs fail closed; do not substitute consensus/closing data.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import argparse
import json
import math
import random

SUPPORTED = {"NFL", "NCAAF", "NCAAB"}
EDGE_GATE = {"spread": .025, "total": .030, "moneyline": .030}
MANDATORY = ("event_id", "season", "sport", "market", "selection", "line",
             "american_odds", "opposing_american_odds", "book", "quote_time_utc",
             "forecast_time_utc", "start_time_utc", "home_score", "away_score",
             "p_win", "p_push", "p_loss", "scope", "model_version",
             "model_provenance_sha256", "quote_provenance_sha256",
             "source_url", "quote_source_url")
SCHEMA_VERSION = "market-holdout-audit-v1"

def instant(value):
    x = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if x.tzinfo is None:
        raise ValueError("Timestamps must be UTC-offset aware")
    return x.astimezone(timezone.utc)

def odds_profit(american):
    if type(american) not in (int, float) or not math.isfinite(american) or (
        american != int(american)) or (-100 < american < 100):
        raise ValueError("invalid American odds")
    return american/100 if american > 0 else 100/(-american)

def implied(american):
    return 1/(1+odds_profit(american))

def settlement(row):
    margin = row["home_score"] - row["away_score"]
    market = row["market"]
    side = row["selection"]
    if market == "moneyline":
        # NFL ties refund; basketball full-game/tournament moneyline ties impossible.
        outcome = margin if side == "home" else -margin
    elif market == "spread":
        if row["line"] is None or not math.isfinite(float(row["line"])):
            raise ValueError("spread missing numeric selected-side handicap")
        handicap = float(row["line"])
        if handicap * 2 != round(handicap * 2):
            raise ValueError("spread quarter lines not supported")
        outcome = (margin if side == "home" else -margin) + handicap
    elif market == "total":
        if row["line"] is None or not math.isfinite(float(row["line"])):
            raise ValueError("total missing numeric threshold")
        threshold = float(row["line"])
        if threshold * 2 != round(threshold * 2):
            raise ValueError("total quarter lines not supported")
        outcome = row["home_score"]+row["away_score"]-threshold
        if side == "under":
            outcome = -outcome
    else:
        raise ValueError("invalid market")
    return 1 if outcome > 0 else -1 if outcome < 0 else 0

def checked(row):
    missing = [key for key in MANDATORY if key not in row or row[key] is None]
    if missing:
        raise ValueError("missing mandatory fields: " + ", ".join(missing))
    sport, market, side = row["sport"], row["market"], row["selection"]
    if sport not in SUPPORTED or market not in EDGE_GATE:
        raise ValueError("unsupported sport/market")
    if side not in (("home","away") if market in ("moneyline","spread")
                    else ("over","under")):
        raise ValueError("incorrect selection for market")
    if str(row["scope"]) != "full_game_including_overtime":
        raise ValueError("unsupported settlement scope")
    if market == "moneyline" and row["line"] not in ("", "NA", "N/A", 0):
        raise ValueError("moneyline must not carry a spread/total threshold")
    if any(type(row[k]) not in (int,float) or not math.isfinite(row[k])
           or row[k] < 0 or row[k] != int(row[k])
           for k in ("home_score","away_score")):
        raise ValueError("final scores must be nonnegative integers")
    if market == "moneyline" and sport != "NFL" and row["home_score"] == row["away_score"]:
        raise ValueError("completed basketball/college football full game cannot tie")
    if int(row["season"]) < 2000 or int(row["season"]) > 2050:
        raise ValueError("invalid season")
    f,q,k=(instant(row[field]) for field in
           ("forecast_time_utc","quote_time_utc","start_time_utc"))
    if f >= k or q >= k:
        raise ValueError("post-start forecast/quote not permitted")
    if q < f:
        # Market-blind forecasts may precede the sportsbook observation.
        pass
    if not str(row["book"]).strip() or not str(row["event_id"]).strip():
        raise ValueError("book and event_id required")
    if any(not str(row[key]).strip() for key in
           ("model_version","model_provenance_sha256",
            "quote_provenance_sha256","source_url","quote_source_url")):
        raise ValueError("provenance required")
    if not all(math.isfinite(float(row[k])) and 0 <= float(row[k]) <= 1
               for k in ("p_win","p_push","p_loss")):
        raise ValueError("invalid model probabilities")
    if not math.isclose(sum(float(row[k]) for k in ("p_win","p_push","p_loss")),
                        1, abs_tol=1e-8):
        raise ValueError("three-way probabilities must sum to one")
    if 1-float(row["p_push"]) < 1e-8:
        raise ValueError("all probability mass is push")
    payout=odds_profit(row["american_odds"])
    opp_payout=odds_profit(row["opposing_american_odds"])
    # Opposite side must be the same book, event, market, line and time as
    # primary offer; caller declares these paired quote fields in one row.
    # 'market_pair_verified' is an evidence requirement, not an agent inference.
    if row.get("market_pair_verified") is not True:
        raise ValueError("same-book paired opposing quote not independently verified")
    # The conditional non-push market benchmark is meaningful at the SAME line.
    market_1=1/(1+payout)
    market_2=1/(1+opp_payout)
    market_novig=market_1/(market_1+market_2)
    p=float(row["p_win"]);push=float(row["p_push"]);loss=float(row["p_loss"])
    model_cond=p/(1-push)
    decision=int(settlement(row))
    if decision == 0 and abs(float(row["line"] or 0)*2-round(float(row["line"] or 0)*2))>1e-9:
        raise ValueError("impossible push at half point")
    edge=model_cond-market_1
    expected=p*payout-loss
    selected=(edge >= EDGE_GATE[market] and expected > 0)
    actual_profit=(payout if decision==1 else -1 if decision == -1 else 0)
    return {
        "event_id":str(row["event_id"]), "season":int(row["season"]),
        "sport":sport,"market":market,"selection":side,
        "book":row["book"],"quote_time_utc":str(row["quote_time_utc"]),
        "model_version":str(row["model_version"]),
        "outcome":decision,"model_conditional_win":model_cond,
        "no_vig_conditional_win":market_novig,"conditional_breakeven":market_1,
        "model_push":push,"model_expected_roi":expected,
        "conditional_edge":edge,"hypothetical_selected":selected,
        "hypothetical_profit_per_1_risk":actual_profit if selected else 0.,
        "forecast_key":sha256(json.dumps(
            [row["event_id"],sport,market,side,row["line"],row["book"],
             row["quote_time_utc"],row["forecast_time_utc"]],
            separators=(",",":")).encode()).hexdigest()[:32]
    }

def metrics(rows):
    usable=[r for r in rows if r["outcome"] != 0]
    def brier(kind):
        return sum((r[kind]-(r["outcome"]==1))**2 for r in usable)/len(usable) if usable else None
    selections=[r for r in rows if r["hypothetical_selected"]]
    pnl=sum(r["hypothetical_profit_per_1_risk"] for r in selections)
    return {"quotes":len(rows),"nonpush":len(usable),
            "pushes":len(rows)-len(usable),
            "model_conditional_brier":brier("model_conditional_win"),
            "same_quote_novig_conditional_brier":brier("no_vig_conditional_win"),
            "hypothetical_selected":len(selections),
            "hypothetical_net_units_risked":len(selections),
            "hypothetical_profit_units":pnl,
            "hypothetical_roi":pnl/len(selections) if selections else None}

def bootstrap_ci(rows, *, iterations=1000, seed=20261103):
    """Paired event-cluster percentile CI, not a green-light performance proof."""
    if not rows:
        return None
    groups=defaultdict(list)
    for r in rows:
        groups[(r["sport"],r["season"],r["event_id"])].append(r)
    keys=list(groups)
    rng=random.Random(seed)
    deltas=[]; rois=[]
    for _ in range(iterations):
        draw=[r for key in (rng.choice(keys) for __ in keys) for r in groups[key]]
        nonpush=[r for r in draw if r["outcome"]]
        if nonpush:
            b=lambda key:sum((r[key]-(r["outcome"]==1))**2 for r in nonpush)/len(nonpush)
            deltas.append(b("model_conditional_win")-b("no_vig_conditional_win"))
        selections=[r for r in draw if r["hypothetical_selected"]]
        if selections:
            rois.append(sum(r["hypothetical_profit_per_1_risk"] for r in selections)/len(selections))
    def percentile_interval(x):
        if not x:return None
        x.sort()
        return [x[int(.025*(len(x)-1))], x[int(.975*(len(x)-1))]]
    return {"paired_model_minus_market_brier_95pct":percentile_interval(deltas),
            "hypothetical_roi_95pct":percentile_interval(rois),
            "cluster_count":len(keys),"replicates":iterations}

def audit(path: Path, *, min_coverage_events=300):
    raw=path.read_bytes()
    rows=[]; errors=[]; seen=set()
    lines=[line for line in raw.decode("utf-8").splitlines() if line.strip()]
    for index,line in enumerate(lines,1):
        try:
            row=json.loads(line)
            result=checked(row)
            if result["forecast_key"] in seen:
                raise ValueError("duplicate immutable forecast key")
            seen.add(result["forecast_key"])
            rows.append(result)
        except (ValueError,TypeError,KeyError,OverflowError) as exc:
            errors.append({"line":index,"reason":str(exc)})
    by_sport={}
    for sport in sorted(SUPPORTED):
        chosen=[r for r in rows if r["sport"]==sport]
        by_year={str(y):metrics([r for r in chosen if r["season"]==y])
                 for y in sorted({r["season"] for r in chosen})}
        ids={r["event_id"] for r in chosen}
        by_sport[sport]={"coverage":{"valid_quotes":len(chosen),
                                    "unique_events":len(ids),
                                    "historical_seasons":len(by_year)},
                         "metrics":metrics(chosen),"by_season":by_year,
                         "cluster_ci":bootstrap_ci(chosen),
                         "production_approved":False,
                         "blocker":("No independently authenticated source coverage review;"
                                    " caller-supplied observed timestamps and evidence"
                                    " are not independently proven by this audit")
                         if len(ids)>=min_coverage_events else
                         "Insufficient independently verifiable same-book historical market coverage"}
    return {"schema":SCHEMA_VERSION,
            "input_sha256":sha256(raw).hexdigest(),
            "read_rows":len(lines),"accepted":len(rows),
            "rejected":len(errors),"rejection_examples":errors[:25],
            "sports":by_sport,
            "approval":"RESEARCH_ONLY",
            "official_wagers_changed":0,
            "approved_live_risk_usd":0,
            "warnings":[
                "Input timestamps/quote-original provenance require independent audit",
                "Same-book market-no-vig conditional baseline, not a guaranteed fair probability",
                "No claims of verified sportsbook execution, CLV, or retrospective real wagers",
                "Selection criteria frozen at 2.5pp spread and 3pp total/moneyline",
                "No model promoted without proper held-out training and real historical market coverage"
            ]}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--input",type=Path,required=True,
                        help="Private JSONL records, not official wagers")
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    if args.input.resolve()==args.output.resolve():
        raise SystemExit("Cannot overwrite immutable source")
    report=audit(args.input)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    if args.output.exists():
        raise SystemExit("Refusing to overwrite existing audit")
    with args.output.open("x",encoding="utf-8") as target:
        json.dump(report,target,indent=2,allow_nan=False)
    print(json.dumps({"accepted":report["accepted"],"rejected":report["rejected"],
                      "sports":{k:v["coverage"] for k,v in report["sports"].items()},
                      "approval":report["approval"]}))

if __name__=="__main__":
    main()
