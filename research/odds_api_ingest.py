"""Capture reproducible original market snapshots for NFL, FBS and men's NCAAB.

Optional paid The Odds API provider. Never stores the API key in artifacts/logs.
Creates PRIVATE research-only quote observations; does not calculate model p,
does not convert market odds into probabilities, and does not touch wagers.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import requests

SPORT_KEYS={"NFL":"americanfootball_nfl","NCAAF":"americanfootball_ncaaf",
            "NCAAB":"basketball_ncaab"}
ENDPOINT="https://api.the-odds-api.com/v4"

def utc(value):
    dt=datetime.fromisoformat(str(value).replace("Z","+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Provider time lacks timezone")
    return dt.astimezone(timezone.utc)

def odds(value):
    if type(value) is not int or -100 < value < 100:
        raise ValueError("Not valid American odds")
    return value

def normalize(payload, sport, *, historical=True):
    """Accept unmodified provider JSON; preserve exact market timestamps.

    Market odds can be separated by asynchronous 'last_update'; never pair
    prices across bookmakers or different market updates.
    """
    if sport not in SPORT_KEYS:
        raise ValueError("Unsupported sport")
    snapshot = utc(payload["timestamp"]) if historical else None
    games = payload["data"] if historical else payload
    if not isinstance(games,list):
        raise ValueError("Provider games must be a list")
    rows=[]; rejected=[]
    for game in games:
        try:
            start=utc(game["commence_time"])
            if historical and snapshot >= start:
                continue
            home,away=str(game["home_team"]),str(game["away_team"])
            gid=str(game["id"])
            for book in game.get("bookmakers",[]):
                book_id=str(book["key"])
                for market in book.get("markets",[]):
                    name=market.get("key")
                    if name not in ("h2h","spreads","totals"):
                        continue
                    market_time=utc(market.get("last_update") or book["last_update"])
                    if market_time >= start:
                        continue
                    if historical and market_time > snapshot:
                        rejected.append({"event_id":gid,"book":book_id,"market":name,
                                         "error":"book quote newer than historic snapshot"})
                        continue
                    choices=market.get("outcomes",[])
                    if not isinstance(choices,list):
                        raise ValueError("Bad market outcomes")
                    outcome_map={str(x["name"]):x for x in choices}
                    if name in ("spreads","h2h"):
                        left,right=outcome_map.get(home),outcome_map.get(away)
                        sides=[("home",left,right),("away",right,left)]
                    else:
                        over,under=outcome_map.get("Over"),outcome_map.get("Under")
                        sides=[("over",over,under),("under",under,over)]
                    if any(item is None for _,a,b in sides for item in (a,b)):
                        continue
                    for side,selection,opposite in sides:
                        price=odds(selection["price"])
                        other_price=odds(opposite["price"])
                        if name == "h2h":
                            line,other_line="",""
                        elif name=="spreads":
                            line=float(selection["point"])
                            other_line=float(opposite["point"])
                            if abs(line+other_line)>1e-9:
                                continue
                        else:
                            line=float(selection["point"])
                            other_line=float(opposite["point"])
                            if abs(line-other_line)>1e-9:
                                continue
                        import math
                        if name != "h2h" and (
                            not math.isfinite(line) or not math.isfinite(other_line) or
                            line * 2 != round(line*2)):
                            # Quarter Asian lines and malformed prices need separate grading.
                            continue
                        rows.append({
                            "event_id":gid, "sport":sport,
                            "home":home,"away":away, "start_time_utc":start.isoformat(),
                            "market":{"h2h":"moneyline","spreads":"spread",
                                      "totals":"total"}[name],
                            "selection":side, "line":line,
                            "american_odds":price,
                            "opposing_american_odds":other_price,
                            "opposing_line":other_line,
                            "book":book_id,"opposing_book":book_id,
                            "quote_time_utc":market_time.isoformat(),
                            "opposing_quote_time_utc":market_time.isoformat(),
                            "market_pair_verified":True,
                            "provider_market_snapshot_utc":snapshot.isoformat()
                               if snapshot else None,
                            "provider":"the-odds-api",
                            "quote_evidence_status":"PROVIDER-REPORTED; source originality independent audit pending",
                        })
        except (ValueError,KeyError,TypeError,OverflowError) as exc:
            rejected.append({"event_id":game.get("id","unknown"),"error":str(exc)})
    keys=set();unique=[]
    for row in rows:
        key=(row["event_id"],row["book"],row["market"],row["selection"],
             row["line"],row["american_odds"],row["quote_time_utc"])
        if key in keys:continue
        keys.add(key);unique.append(row)
    return unique,rejected

def collect(sport,mode,output_dir,at=None):
    if sport not in SPORT_KEYS or mode not in ("historical","live"):
        raise ValueError("unsupported sport or mode")
    if mode=="historical" and not at:
        raise ValueError("historical capture must have a specified UTC instant")
    token=os.environ.get("THE_ODDS_API_KEY")
    if not token:
        raise RuntimeError("THE_ODDS_API_KEY not supplied securely")
    if mode=="historical":
        base=f"{ENDPOINT}/historical/sports/{SPORT_KEYS[sport]}/odds"
    else:
        base=f"{ENDPOINT}/sports/{SPORT_KEYS[sport]}/odds"
    params={"apiKey":token,"regions":"us","markets":"h2h,spreads,totals",
            "oddsFormat":"american","dateFormat":"iso"}
    if mode=="historical":
        params["date"]=utc(at).isoformat().replace("+00:00","Z")
    response=requests.get(base,params=params,timeout=50)
    if response.status_code in (401,402,403):
        raise RuntimeError("Provider historical/live data requires authorized subscription")
    response.raise_for_status()
    raw=response.content
    payload=json.loads(raw)
    if mode=="historical" and utc(payload["timestamp"])>utc(at):
        raise RuntimeError("Historical provider returned later-than-requested snapshot")
    rows,rejected=normalize(payload,sport,historical=mode=="historical")
    folder=Path(output_dir)
    folder.mkdir(parents=True,exist_ok=False)
    # Do not put credentials, signed URLs, personal tickets, API response
    # headers or billing metadata in outputs.
    digest=sha256(raw).hexdigest()
    (folder/"provider_raw.json").write_bytes(raw)
    with (folder/"paired_quotes.jsonl").open("x",encoding="utf-8") as f:
        for row in rows:
            row["quote_provenance_sha256"]=digest
            row["quote_source_url"]=base  # API key intentionally omitted
            f.write(json.dumps(row,sort_keys=True)+"\n")
    receipt={
        "source_api":base,"sport":sport,"mode":mode,"requested_at_utc":at,
        "raw_sha256":digest,
        "capture_received_utc":datetime.now(timezone.utc).isoformat(),
        "provider_snapshot_utc":payload.get("timestamp") if mode=="historical" else None,
        "quotes":len(rows),"excluded":len(rejected),
        "excluded_examples":rejected[:20],
        "warning":"Provider quote snapshots alone do not prove independent model p, holdout ROI, CLV, or executable Hard Rock prices"
    }
    (folder/"manifest.json").write_text(json.dumps(receipt,indent=2))
    return receipt

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--sport",choices=sorted(SPORT_KEYS),required=True)
    p.add_argument("--mode",choices=["historical","live"],required=True)
    p.add_argument("--at",help="UTC timestamp required only for historical snapshots")
    p.add_argument("--output-dir",required=True)
    args=p.parse_args()
    r=collect(args.sport,args.mode,args.output_dir,args.at)
    print(json.dumps({k:r[k] for k in ("sport","mode","quotes","excluded",
                                     "provider_snapshot_utc")},indent=2))

if __name__=="__main__":
    main()
