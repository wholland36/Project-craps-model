"""Independent chronological NFL / NCAA FBS historical probability research.

Inputs are historical score schedules. Test years are 2022-25, with the preceding
season reserved for residual calibration. Research-only: historical book quotes,
injury/roster and weather vintages are not verified. No live bet recommendation.
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

NFL_URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
NCAA_URL = "https://raw.githubusercontent.com/sportsdataverse/cfbfastR-data/main/schedules/csv/cfb_schedules_{year}.csv"
FEATURE_NAMES = ["home_attack", "home_defense", "away_attack", "away_defense",
                 "elo_difference", "home_games_prior", "away_games_prior"]

def load_schedules(sport: str, min_year: int = 2010) -> pd.DataFrame:
    if sport == "NFL":
        response = requests.get(NFL_URL, timeout=90)
        response.raise_for_status()
        d = pd.read_csv(io.BytesIO(response.content), low_memory=False)
        d = d.loc[d.game_type.eq("REG") & d.season.between(min_year, 2025)].copy()
        d = d.rename(columns={"gameday": "date_raw", "home_score": "home_points",
                              "away_score": "away_points"})
    elif sport == "NCAAF":
        chunks = []
        for year in range(max(2016, min_year), 2026):
            response = requests.get(NCAA_URL.format(year=year), timeout=90)
            response.raise_for_status()
            x = pd.read_csv(io.BytesIO(response.content), low_memory=False)
            required = {"season", "start_date", "home_team", "away_team",
                        "home_points", "away_points", "home_division", "away_division"}
            missing = required.difference(x.columns)
            if missing:
                raise ValueError(f"{year} data lacks required columns: {sorted(missing)}")
            x = x.loc[x.home_division.eq("fbs") & x.away_division.eq("fbs")].copy()
            x["date_raw"] = x["start_date"]
            chunks.append(x)
        d = pd.concat(chunks, ignore_index=True)
    else:
        raise ValueError("Choose NFL or NCAAF")
    required = ["season", "date_raw", "home_team", "away_team", "home_points", "away_points"]
    d = d.dropna(subset=required).copy()
    d["date"] = pd.to_datetime(d.date_raw, utc=True, errors="coerce")
    d = d.dropna(subset=["date"])
    d["season"] = pd.to_numeric(d.season, errors="raise").astype(int)
    d["home_points"] = pd.to_numeric(d.home_points, errors="coerce")
    d["away_points"] = pd.to_numeric(d.away_points, errors="coerce")
    d = d.dropna(subset=["home_points", "away_points"])
    d = d.sort_values(["date", "home_team", "away_team"]).drop_duplicates(
        ["date", "home_team", "away_team"], keep="first").reset_index(drop=True)
    if d.empty:
        raise ValueError("No real historical games were retrieved")
    return d

def build_causal_features(d: pd.DataFrame) -> np.ndarray:
    """All games on the same calendar date see the same prior state."""
    state = {}
    def get(team: str):
        return state.setdefault(team, {"off": 24., "def": 24., "elo": 1500., "n": 0})
    result = np.zeros((len(d), len(FEATURE_NAMES)), dtype=float)
    groups = d.groupby(d.date.dt.date, sort=True).indices
    for _, indices in sorted(groups.items()):
        changes = []
        for i in indices:
            game = d.iloc[int(i)]
            h, a = get(str(game.home_team)).copy(), get(str(game.away_team)).copy()
            result[i] = [h["off"], h["def"], a["off"], a["def"],
                         h["elo"]-a["elo"], h["n"], a["n"]]
            changes.append((str(game.home_team), str(game.away_team),
                            float(game.home_points), float(game.away_points)))
        # Defer any learning to after feature capture for this whole day.
        for home, away, hs, aws in changes:
            h, a = get(home), get(away)
            expected = 1 / (1 + 10 ** ((a["elo"] - h["elo"]) / 400))
            delta = 20 * ((1 if hs > aws else 0 if hs < aws else .5) - expected)
            h["elo"] += delta
            a["elo"] -= delta
            for team, scored, conceded in ((home, hs, aws), (away, aws, hs)):
                current = get(team)
                current["off"] = .85 * current["off"] + .15 * scored
                current["def"] = .85 * current["def"] + .15 * conceded
                current["n"] += 1
    if not np.isfinite(result).all():
        raise ValueError("Nonfinite historical features")
    return result

def three_way_from_residuals(means: np.ndarray, residuals: np.ndarray,
                             thresholds: np.ndarray) -> np.ndarray:
    """Empirical residual draws with integer-score discretization for pushes.

    For spread threshold q of the home margin, home-cover is margin>q.
    Integer score margins can push on integer q only.
    """
    draws = np.rint(means[:, None] + residuals[None, :])
    threshold = thresholds[:, None]
    return np.column_stack([(draws > threshold).mean(axis=1),
                            (draws == threshold).mean(axis=1),
                            (draws < threshold).mean(axis=1)])

def metric_binary(y: np.ndarray, p: np.ndarray) -> dict:
    p = np.clip(p, 1e-6, 1-1e-6)
    return {"n": int(len(y)), "brier": float(brier_score_loss(y, p)),
            "log_loss": float(log_loss(y, p, labels=[0, 1]))}

def train(sport: str, d: pd.DataFrame) -> dict:
    X = build_causal_features(d)
    yr = d.season.to_numpy()
    margin = (d.home_points - d.away_points).to_numpy(dtype=float)
    total = (d.home_points + d.away_points).to_numpy(dtype=float)
    folds = []
    for year in (2022, 2023, 2024, 2025):
        train_mask, cal_mask, test_mask = yr <= year-2, yr == year-1, yr == year
        if min(train_mask.sum(), cal_mask.sum(), test_mask.sum()) < (150 if sport == "NFL" else 350):
            continue
        models = {}
        values = {}
        for name, truth in (("margin", margin), ("total", total)):
            model = Ridge(alpha=1000 if sport == "NFL" else 1500)
            model.fit(X[train_mask], truth[train_mask])
            models[name] = model
            values[name] = {"prediction": model.predict(X[test_mask]),
                            "cal_residual": truth[cal_mask] - model.predict(X[cal_mask]),
                            "actual": truth[test_mask]}
        mu, residuals = values["margin"]["prediction"], values["margin"]["cal_residual"]
        dist = three_way_from_residuals(mu, residuals, np.zeros(len(mu)))
        truth = (margin[test_mask] > 0).astype(int)
        # A tie is not a win; probability win (not push-adjusted) reported separately.
        model_metrics = metric_binary(truth, dist[:, 0])
        baseline_p = np.full(len(truth), (margin[train_mask] > 0).mean())
        baseline = metric_binary(truth, baseline_p)
        report = {"test_year": year, "train_games": int(train_mask.sum()),
                  "calibration_games": int(cal_mask.sum()),
                  "test_games": int(test_mask.sum()),
                  "home_win_model": model_metrics,
                  "historical_home_rate_baseline": baseline,
                  "margin_MAE": float(mean_absolute_error(margin[test_mask], mu)),
                  "total_MAE": float(mean_absolute_error(total[test_mask], values["total"]["prediction"])),
                  "model_vs_constant_home_rate_brier_delta": model_metrics["brier"] - baseline["brier"]}
        # Market baseline is descriptive only: closing/opening/as-of quote timing unresolved.
        subset = d.loc[test_mask]
        if sport == "NFL" and {"home_moneyline", "away_moneyline"}.issubset(subset.columns):
            home = pd.to_numeric(subset.home_moneyline, errors="coerce").to_numpy()
            away = pd.to_numeric(subset.away_moneyline, errors="coerce").to_numpy()
            ok = np.isfinite(home) & np.isfinite(away) & (home != 0) & (away != 0)
            if ok.any():
                def implied(odds):
                    return np.where(odds < 0, -odds / (100 - odds), 100 / (100 + odds))
                h, a = implied(home[ok]), implied(away[ok])
                baseline_m = metric_binary(truth[ok], h / (h+a))
                report["unverified_quote_market_no_vig"] = baseline_m
                report["model_same_quote_games"] = metric_binary(truth[ok], dist[ok, 0])
                report["unverified_quote_coverage"] = int(ok.sum())
        # The pregame Elo baseline is derived from features built from older games only.
        elo_p = 1 / (1 + 10 ** (-X[test_mask, 4] / 400))
        report["causal_pregame_elo_baseline"] = metric_binary(truth, elo_p)
        # Calibration sample only, not future bookmaker lines.
        thresholds = np.full(len(mu), 3.)
        d3 = three_way_from_residuals(mu, residuals, thresholds)
        report["synthetic_home_margin_gt3"] = {
            "win_probability_mean": float(d3[:, 0].mean()),
            "push_probability_mean": float(d3[:, 1].mean()),
            "loss_probability_mean": float(d3[:, 2].mean()),
            "note": "Not a sportsbook wager and not a betting ROI"}
        folds.append(report)
    if not folds:
        raise ValueError("Insufficient samples for full forward-chaining folds")
    return {"sport": sport, "approval": "RESEARCH ONLY",
            "source": NFL_URL if sport == "NFL" else NCAA_URL,
            "games": int(len(d)), "features": FEATURE_NAMES, "folds": folds,
            "limitations": [
                "No verified timestamped same-book pregame odds or betting holdout ROI",
                "No as-of injury/starting quarterback/weather historical revisions",
                "No approved 2026 season live update or production calibration",
                "No verified holdout improvement against all required market baselines",
                "No production wagering model release; NOT_COMPUTED for today's games"
            ]}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sport", required=True, choices=["NFL", "NCAAF"])
    parser.add_argument("--output", type=Path, default=Path("results/football_research.json"))
    args = parser.parse_args()
    d = load_schedules(args.sport)
    report = train(args.sport, d)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"sport": args.sport, "games": report["games"],
                      "folds": len(report["folds"]), "approval": "RESEARCH ONLY",
                      "output": str(args.output)}))

if __name__ == "__main__":
    main()
