import io, json, requests
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.metrics import brier_score_loss, log_loss, mean_absolute_error

URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
r = requests.get(URL, timeout=90); r.raise_for_status()
d = pd.read_csv(io.BytesIO(r.content), low_memory=False)
d = d[d.game_type.eq("REG") & d.season.between(2010, 2025)].copy()
d = d.dropna(subset=["gameday","home_team","away_team","home_score","away_score"])
d["date"] = pd.to_datetime(d.gameday, errors="coerce")
d = d.dropna(subset=["date"]).sort_values(["date","game_id"]).reset_index(drop=True)
# All feature updates occur only after every game on the same date.
state = {}
def get(team):
    return state.setdefault(team, {"attack":22., "defense":22., "elo":1500., "n":0})
features = []
for day, group in d.groupby("date", sort=True):
    changes = []
    for i,g in group.iterrows():
        h=get(g.home_team).copy(); a=get(g.away_team).copy()
        features.append((i, [h["attack"],h["defense"],a["attack"],a["defense"],h["elo"]-a["elo"],h["n"],a["n"],float(g.home_rest) if pd.notna(g.home_rest) else 7.,float(g.away_rest) if pd.notna(g.away_rest) else 7.]))
        changes.append((g.home_team,g.away_team,float(g.home_score),float(g.away_score)))
    for home,away,hs,aw in changes:
        h=get(home);a=get(away)
        expected=1/(1+10**((a["elo"]-h["elo"])/400))
        step=20*((1 if hs>aw else 0 if hs<aw else .5)-expected)
        h["elo"]+=step;a["elo"]-=step
        for name,sc,opp in ((home,hs,aw),(away,aw,hs)):
            v=get(name);v["attack"] = .84*v["attack"]+.16*sc
            v["defense"] = .84*v["defense"]+.16*opp
            v["n"]+=1

X=np.array([v for _,v in features],dtype=float)
assert len(X)==len(d)
margin=(d.home_score-d.away_score).to_numpy(dtype=float)
total=(d.home_score+d.away_score).to_numpy(dtype=float)
season=d.season.to_numpy()
train=season<=2023; valid=season==2024; test=season==2025
assert min(train.sum(),valid.sum(),test.sum())>200
pm=Ridge(alpha=1000).fit(X[train],margin[train])
pt=Ridge(alpha=1000).fit(X[train],total[train])
pred_m=pm.predict(X[test]);pred_t=pt.predict(X[test])
res_m=margin[valid]-pm.predict(X[valid])
res_t=total[valid]-pt.predict(X[valid])
def distp(mean, resid, threshold):
    return np.clip(np.array([(resid > (z-m)).mean() for m,z in zip(mean,threshold)]),.005,.995)
pwin=distp(pred_m,res_m,np.zeros(test.sum()))
truth=(margin[test]>0).astype(int)
report={
  "dataset":"nflverse nfldata games.csv regular-season scores",
  "population":"NFL regular season",
  "train_n":int(train.sum()),"validation_n":int(valid.sum()),"holdout_n":int(test.sum()),
  "holdout_season":2025,
  "margin_MAE":float(mean_absolute_error(margin[test],pred_m)),
  "total_MAE":float(mean_absolute_error(total[test],pred_t)),
  "homewin_brier":float(brier_score_loss(truth,pwin)),
  "homewin_logloss":float(log_loss(truth,pwin,labels=[0,1])),
  "historical_home_rate_brier":float(brier_score_loss(truth,np.full(len(truth),(margin[train]>0).mean()))),
  "sport":"NFL","model":"market-blind causal rolling score and Elo Ridge baseline",
  "approval":"RESEARCH ONLY"}
# Historical book prices available in source; grade spreads and totals with unaltered prices.
test_df=d.loc[test].reset_index(drop=True)
def betprob(mu,resid,line): return np.clip(np.array([(resid > (-l - m)).mean() for m,l in zip(mu,line)]),.005,.995)
def american_profit(odds):return np.where(odds>0,odds/100.,100./(-odds))
def market_analysis(pred, res, line_col, positive_odds, negative_odds, real, is_total=False):
    line=pd.to_numeric(test_df[line_col],errors="coerce").to_numpy()
    o1=pd.to_numeric(test_df[positive_odds],errors="coerce").to_numpy()
    o2=pd.to_numeric(test_df[negative_odds],errors="coerce").to_numpy()
    ok=np.isfinite(line)&np.isfinite(o1)&np.isfinite(o2)&(o1!=0)&(o2!=0)
    if not ok.any():return {"coverage":0}
    # For spread: home wins if home margin > -spread_line; for total: Over wins if total > total_line
    threshold=line.copy() if is_total else -line.copy()
    prob=np.clip(np.array([(res>q-m).mean() for m,q in zip(pred,threshold)]),.005,.995)
    # o1 = home spread odds or Over odds; o2 = away spread or Under odds.
    ratio1=american_profit(o1);ratio2=american_profit(o2)
    ev1=prob*ratio1-(1-prob)
    ev2=(1-prob)*ratio2-prob
    picks=ok & (np.maximum(ev1,ev2)>.05)  # exploratory fixed 5% minimum estimated ROI
    choose1=ev1>ev2
    outcome=np.where(choose1,real>threshold,real<threshold)
    push=real==threshold
    realized=np.where(push,0,np.where(outcome,np.where(choose1,ratio1,ratio2),-1.))
    return {"book_coverage":int(ok.sum()),"selected":int(picks.sum()),"wins":int((picks&outcome&~push).sum()),"losses":int((picks&~outcome&~push).sum()),"pushes":int((picks&push).sum()),"profit_per_1_unit_risked":float(realized[picks].sum()),"roi_on_risk":float(realized[picks].mean()) if picks.any() else None,"warning":"Exploratory 2025 holdout evaluation, not validated for live staking. Book quote timestamps and calibration uncertainty unresolved."}
report["spread_market"]=market_analysis(pred_m,res_m,"spread_line","home_spread_odds","away_spread_odds",margin[test])
report["total_market"]=market_analysis(pred_t,res_t,"total_line","over_odds","under_odds",total[test],True)
with open("results/nfl_report.json","w") as f:json.dump(report,f,indent=2)
with open("results/nfl_parameters.json","w") as f:json.dump({"features":["home_attack","home_defense","away_attack","away_defense","elo_diff","home_games","away_games","home_rest","away_rest"],"margin_coefs":pm.coef_.tolist(),"margin_intercept":float(pm.intercept_),"total_coefs":pt.coef_.tolist(),"total_intercept":float(pt.intercept_),"validation_residual_margin":res_m.tolist(),"validation_residual_total":res_t.tolist(),"training_cutoff":"2023-12-31","note":"Research only; needs 2026 rolling updates and validation before any live probability"},f)
print(json.dumps(report,indent=2))
