"""Project Craps NCAAB historical probability research, NOT a production betting model.

Source: NCAA Men's Basketball schedules published by sportsdataverse.
Season is the *starting* year: 2025 means the 2025-26 season.
No private wager data or API keys are used. No sportsbook odds are presumed.
"""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import numpy as np
import pandas as pd
import requests
from sklearn.linear_model import Ridge
from sklearn.metrics import brier_score_loss, log_loss, mean_absolute_error

URL = ("https://github.com/sportsdataverse/sportsdataverse-data/releases/"
       "download/ncaa_mbb_schedule/ncaa_mbb_schedule_{year}.parquet")
FEATURES = ("home_for", "home_against", "away_for", "away_against",
            "home_elo_minus_away_elo", "home_games", "away_games",
            "home_days_rest", "away_days_rest")
TRAIN_START = 2016
LAST_COMPLETE_SEASON = 2025

def load_games(first_year: int = TRAIN_START, last_year: int = LAST_COMPLETE_SEASON):
    chunks = []
    for year in range(first_year, last_year + 1):
        response = requests.get(URL.format(year=year), timeout=90)
        response.raise_for_status()
        df = pd.read_parquet(io.BytesIO(response.content))
        columns = {"contest_id", "game_date", "home", "away", "home_score", "away_score", "season"}
        missing = columns - set(df.columns)
        if missing:
            raise ValueError(f"Source {year} missing {sorted(missing)}")
        df = df[list(columns)].copy()
        df["source_season"] = year
        chunks.append(df)
    data = pd.concat(chunks, ignore_index=True)
    data["date"] = pd.to_datetime(data.game_date, errors="coerce", utc=True)
    for key in ("home_score", "away_score", "season"):
        data[key] = pd.to_numeric(data[key], errors="coerce")
    data = data.dropna(subset=["date", "home", "away", "home_score",
                               "away_score", "season", "contest_id"]).copy()
    data = data.loc[(data.season == data.source_season)
                    & (data.home != data.away)
                    & (data.home_score >= 0)
                    & (data.away_score >= 0)].copy()
    data["home"] = data["home"].astype(str).str.strip()
    data["away"] = data["away"].astype(str).str.strip()
    data = data.drop_duplicates(subset=["contest_id"], keep="first")
    data = data.sort_values(["date", "contest_id"]).reset_index(drop=True)
    if len(data) < 10000:
        raise RuntimeError(f"Historical schedule too thin: {len(data)} complete contests")
    if not set(range(first_year, last_year + 1)).issubset(set(data.season.astype(int))):
        raise RuntimeError("Missing one or more historical seasons")
    return data

def pregame_features(data: pd.DataFrame) -> np.ndarray:
    """Pregame team and opponent-adjusted Elo stats. Date-group isolation is strict.

    Approximate opponent adjustment is through causal Elo; score rolling averages
    alone are NOT independently opponent-adjusted possession metrics.
    """
    state = {}
    X = np.empty((len(data), len(FEATURES)), dtype=float)
    current_season = None

    def get(t):
        return state.setdefault(t, {"for": 70., "against": 70.,
                                    "elo": 1500., "games": 0, "last": None})

    for day, inds in data.groupby(data.date.dt.date, sort=True).indices.items():
        changes = []
        for i in inds:
            game = data.iloc[int(i)]
            year = int(game.season)
            if current_season is None:
                current_season = year
            if year != current_season:
                # The portal makes full carryover assumptions unsafe. Regress priors.
                # On normal winter/spring dates there is only one season.
                for s in state.values():
                    s["for"] = 70. + .20 * (s["for"] - 70.)
                    s["against"] = 70. + .20 * (s["against"] - 70.)
                    s["elo"] = 1500. + .45 * (s["elo"] - 1500.)
                    s["games"] = 0
                    s["last"] = None
                current_season = year
            h = get(str(game.home))
            a = get(str(game.away))
            date = game.date.date()
            rest_h = (date - h["last"]).days if h["last"] else 7
            rest_a = (date - a["last"]).days if a["last"] else 7
            X[int(i)] = (h["for"], h["against"], a["for"], a["against"],
                         h["elo"] - a["elo"], h["games"], a["games"],
                         min(max(rest_h, 0), 15), min(max(rest_a, 0), 15))
            changes.append((str(game.home), str(game.away),
                            float(game.home_score), float(game.away_score), date))
        # Deferred until every game on this UTC date has frozen its pregame input.
        # Doubleheaders are uncommon; update order only changes subsequent days.
        for home, away, hp, ap, date in changes:
            h, a = get(home), get(away)
            expected = 1/(1+10**((a["elo"]-h["elo"])/400))
            delta = 16*((1 if hp>ap else 0 if hp<ap else .5) - expected)
            h["elo"] += delta
            a["elo"] -= delta
            for team, scored, allowed in ((home, hp, ap), (away, ap, hp)):
                s=get(team)
                s["for"] = .87*s["for"] + .13*scored
                s["against"] = .87*s["against"] + .13*allowed
                s["games"] += 1
                s["last"] = date
    if not np.isfinite(X).all():
        raise RuntimeError("Nonfinite pregame features")
    return X

def discrete_three_way(mean: np.ndarray, residual: np.ndarray,
                       line: np.ndarray) -> np.ndarray:
    """Empirical discrete-score Win/Push/Loss for home margin or combined total.

    2024 or preceding validation-only residual draws; never use holdout results.
    At half-point threshold, pushes are mathematically impossible.
    """
    if not len(residual) or not np.isfinite(residual).all():
        raise ValueError("Missing clean calibration residuals")
    draws=np.rint(mean[:,None]+residual[None,:])
    threshold=line[:,None]
    return np.stack(((draws>threshold).mean(axis=1),
                     (draws==threshold).mean(axis=1),
                     (draws<threshold).mean(axis=1)), axis=1)

def scoring(y: np.ndarray, p: np.ndarray) -> dict:
    pp=np.clip(p, 1e-6, 1-1e-6)
    return {"n": int(len(y)), "brier": float(brier_score_loss(y,pp)),
            "log_loss": float(log_loss(y,pp, labels=[0,1]))}

def evaluate(data: pd.DataFrame, X: np.ndarray | None = None) -> dict:
    if X is None:
        X=pregame_features(data)
    season=data.season.to_numpy(dtype=int)
    margins=(data.home_score-data.away_score).to_numpy(dtype=float)
    totals=(data.home_score+data.away_score).to_numpy(dtype=float)
    results=[]
    for testyear in (2022,2023,2024,2025):
        train=season<=testyear-2
        calibrate=season==testyear-1
        test=season==testyear
        if min(train.sum(),calibrate.sum(),test.sum())<1000:
            raise RuntimeError(f"Insufficient pregame sample sizes for {testyear}")
        pred={}
        for name, outcome in (("margin",margins),("total",totals)):
            model=Ridge(alpha=2000.)
            model.fit(X[train],outcome[train])
            pred[name]=(model.predict(X[test]),
                        outcome[calibrate]-model.predict(X[calibrate]))
        margin_mean,margin_res=pred["margin"]
        total_mean,total_res=pred["total"]
        dist=discrete_three_way(margin_mean,margin_res,np.zeros(test.sum()))
        outcome=(margins[test]>0).astype(int)
        home_p=dist[:,0]
        mean_train_home=(margins[train]>0).mean()
        baseline=scoring(outcome,np.full(test.sum(),mean_train_home))
        elo_p=1/(1+10**(-X[test,4]/400))
        # Diagnostic synthetic thresholds: NEVER use as sportsbook prices / ROI.
        margin_d=discrete_three_way(margin_mean, margin_res,
                                    np.full(test.sum(), 3.5))
        total_d=discrete_three_way(total_mean,total_res,
                                   np.full(test.sum(), 145.5))
        results.append({
            "test_season_start_year":int(testyear), "n_train":int(train.sum()),
            "n_calibration":int(calibrate.sum()),"n_holdout":int(test.sum()),
            "home_win":scoring(outcome, home_p),
            "home_rate_baseline":baseline,
            "pregame_elo_baseline":scoring(outcome,elo_p),
            "margin_MAE":float(mean_absolute_error(margins[test],margin_mean)),
            "total_MAE":float(mean_absolute_error(totals[test],total_mean)),
            "synthetic_spread_3p5": {
                "mean_win":float(margin_d[:,0].mean()),
                "mean_push":float(margin_d[:,1].mean()),
                "mean_loss":float(margin_d[:,2].mean())},
            "synthetic_total_145p5": {
                "mean_over":float(total_d[:,0].mean()),
                "mean_push":float(total_d[:,1].mean()),
                "mean_under":float(total_d[:,2].mean())},
            "market_baseline": "UNAVAILABLE: no time-stamped same-event bookmaker quotes",
            "holdout_betting_roi": "NOT_COMPUTED"})
    return {
        "sport":"NCAAB_MEN", "model":"NCAAB score + causal Elo Ridge baseline",
        "release":"RESEARCH ONLY / NOT VALIDATED FOR WAGERING",
        "data_source":URL,"season_definition":"starting calendar year",
        "game_count":int(len(data)), "features":list(FEATURES),
        "forward_chaining":results, "risk_approved_usd":0,
        "blocking_requirements":[
            "Same-game timestamped sportsbook line and price histories unavailable",
            "No source-verified neutral-site flags or venue adjustments",
            "No historical as-of roster, transfer, injury and projected-minutes data",
            "Full possessions-adjusted opponent efficiency and pace not available",
            "No multi-season price-specific push-aware betting ROI with confidence intervals",
            "No independent market no-vig baseline on identical held-out games",
            "Model has not been safely refreshed/recalibrated for 2026-27 live games",
            "No production release promotion, price feed, or canonical Sheet writeback"]}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,default=Path("results/ncaab_men_research.json"))
    args=parser.parse_args()
    d=load_games()
    result=evaluate(d)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,allow_nan=False),encoding="utf-8")
    print(json.dumps({"games":result["game_count"],
                      "folds":len(result["forward_chaining"]),
                      "status":result["release"],"file":str(args.output)}))

if __name__=="__main__":
    main()
