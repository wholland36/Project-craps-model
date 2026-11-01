import io,json,requests,numpy as np,pandas as pd
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error,brier_score_loss,log_loss
rows=[]
for year in range(2016,2026):
    url=f'https://raw.githubusercontent.com/sportsdataverse/cfbfastR-data/main/schedules/csv/cfb_schedules_{year}.csv'
    r=requests.get(url,timeout=90);r.raise_for_status()
    d=pd.read_csv(io.BytesIO(r.content),low_memory=False)
    needed=['season','start_date','home_team','away_team','home_points','away_points','home_division','away_division','home_pregame_elo','away_pregame_elo']
    missing=[c for c in needed if c not in d.columns]
    if missing: raise RuntimeError(f'{year}: missing {missing}')
    d=d.dropna(subset=['season','start_date','home_team','away_team','home_points','away_points']).copy()
    d=d[d.home_division.eq('fbs') & d.away_division.eq('fbs')].copy()
    d=d[d.season.astype(int).eq(year)]
    d['date']=pd.to_datetime(d.start_date,utc=True,errors='coerce')
    d=d.dropna(subset=['date'])
    rows.append(d[['date','season','home_team','away_team','home_points','away_points','home_pregame_elo','away_pregame_elo']])
    print(year,len(d),flush=True)
games=pd.concat(rows).sort_values('date').drop_duplicates(['date','home_team','away_team'])
games=games[(games.season>=2016)&(games.season<=2025)].copy()
if len(games)<3000: raise RuntimeError(f'Insufficient real FBS-v-FBS historical games {len(games)}')
# Causal rolling opponent-adjusted points and Elo, updated after each game date.
state={}; feats=[]
def s(team):
    return state.setdefault(team,{'for':24.,'against':24.,'n':0,'elo':1500.})
for day,part in games.groupby(games.date.dt.date,sort=True):
    changes=[]
    for idx,g in part.iterrows():
        h=str(g.home_team);a=str(g.away_team);hs=s(h).copy();as_=s(a).copy()
        feats.append((idx,[hs['for'],hs['against'],as_['for'],as_['against'],hs['elo']-as_['elo'],hs['n'],as_['n']]))
        changes.append((h,a,float(g.home_points),float(g.away_points)))
    for h,a,hp,ap in changes:
        sh=s(h);sa=s(a)
        expected=1/(1+10**((sa['elo']-sh['elo'])/400))
        delta=20*((1 if hp>ap else 0 if hp<ap else .5)-expected)
        sh['elo']+=delta;sa['elo']-=delta
        for t,sc,al in ((h,hp,ap),(a,ap,hp)):
            q=s(t);q['for']=.85*q['for']+.15*(sc-(24-s(t)['against'])*.1)
            q['against']=.85*q['against']+.15*al;q['n']+=1
X=np.asarray([v for _,v in feats],dtype=float)
assert X.shape[0]==len(games), (X.shape,len(games))
y=(games.home_points-games.away_points).to_numpy(float)
train=(games.season<=2023).to_numpy()
valid=(games.season==2024).to_numpy()
test=(games.season==2025).to_numpy()
if min(train.sum(),valid.sum(),test.sum())<400:raise RuntimeError('FBS season splits insufficient')
model=Ridge(alpha=1500).fit(X[train],y[train])
# Evaluate test with residual distribution fitted ONLY on validation season
vres=y[valid]-model.predict(X[valid])
pred=model.predict(X[test]); actual=y[test]
homewin=np.array([(vres > -p).mean() for p in pred])
homewin=np.clip(homewin,.005,.995)
result=(actual>0).astype(int)
report={'source':'cfbfastR-data historical schedules','n_train':int(train.sum()),'n_validation':int(valid.sum()),'n_test':int(test.sum()),'test_season':2025,'margin_MAE':float(mean_absolute_error(actual,pred)),'home_win_brier':float(brier_score_loss(result,homewin)),'home_win_logloss':float(log_loss(result,homewin)),'baseline_brier':float(brier_score_loss(result,np.full(len(result),result[valid[:0]].mean() if False else .5))),'warning':'Research baseline only: no historical sportsbook prices, advanced EPA injury data or profitability validation. Not approved for wagering.'}
# External pregame Elo baseline, completely independent of sportsbook lines.
elo_h=pd.to_numeric(games.home_pregame_elo,errors='coerce').to_numpy()
elo_a=pd.to_numeric(games.away_pregame_elo,errors='coerce').to_numpy()
elo_mask=test & np.isfinite(elo_h) & np.isfinite(elo_a)
if elo_mask.sum()>100:
    elo_p=1/(1+10**((elo_a[elo_mask]-elo_h[elo_mask])/400))
    elo_truth=(y[elo_mask]>0).astype(int)
    report['pregame_elo_comparison']={'n':int(elo_mask.sum()),'brier':float(brier_score_loss(elo_truth,elo_p)),
       'model_brier_same_games':float(brier_score_loss(elo_truth,homewin[np.where(test)[0].searchsorted(np.where(elo_mask)[0])]))}
report['population']='FBS vs FBS only, including postseason where present'
# Additional honest 2025 benchmarks; no bookmaker or market lines involved.
from sklearn.metrics import mean_squared_error
home_rate=float(((y[train])>0).mean())
constp=np.full(test.sum(),home_rate)
report['train_home_win_rate']=home_rate
report['home_rate_baseline_brier']=float(brier_score_loss(result,constp))
report['home_rate_baseline_logloss']=float(log_loss(result,constp))
report['zero_margin_MAE']=float(mean_absolute_error(actual,np.zeros(len(actual))))
# Spread/total forecasts require point distributions. Current model predicts margin only;
# do not confuse home-win discrimination with actual spread/total calibration.
report['spread_total_status']='NOT_VALIDATED: no contemporaneous odds, totals distribution or betting prices'
report['test_home_win_rate']=float(result.mean())
report['calibration_buckets']=[]
for lo,hi in [(0,.2),(.2,.4),(.4,.6),(.6,.8),(.8,1.01)]:
    mask=(homewin>=lo)&(homewin<hi)
    if mask.any(): report['calibration_buckets'].append({'range':[lo,hi],'n':int(mask.sum()),'mean_p':float(homewin[mask].mean()),'observed':float(result[mask].mean())})
# Total points model: separate pregame regressor; residuals from 2024 only.
total_y=(games.home_points+games.away_points).to_numpy(float)
total_model=Ridge(alpha=1500).fit(X[train],total_y[train])
total_pred=total_model.predict(X[test])
total_actual=total_y[test]
total_res=total_y[valid]-total_model.predict(X[valid])
report['total_MAE']=float(mean_absolute_error(total_actual,total_pred))
report['total_constant_train_MAE']=float(mean_absolute_error(total_actual,np.full(len(total_actual),total_y[train].mean())))
# Probabilistic market-like calibration test at fixed thresholds derived
# solely from earlier 2024 prediction quantiles, NOT real bookmaker lines.
# Tests correct probability machinery; NOT historical betting ROI.
quantiles=[.2,.4,.6,.8]
margin_grid=np.unique(np.round(np.quantile(model.predict(X[valid]),quantiles)*2)/2)
total_grid=np.unique(np.round(np.quantile(total_model.predict(X[valid]),quantiles)*2)/2)
def binary_eval(y_true,mu,residuals,thresholds):
    out=[]
    for threshold in thresholds:
        p=np.clip(np.array([(residuals>threshold-m).mean() for m in mu]),.005,.995)
        target=(y_true>threshold).astype(int)
        push=(y_true==threshold)
        eligible=~push
        out.append({'threshold':float(threshold),'n':int(eligible.sum()),'pushes':int(push.sum()),
                    'brier':float(brier_score_loss(target[eligible],p[eligible])),
                    'logloss':float(log_loss(target[eligible],p[eligible],labels=[0,1])),
                    'observed_rate':float(target[eligible].mean()),
                    'predicted_rate':float(p[eligible].mean())})
    return out
report['synthetic_margin_threshold_tests']=binary_eval(actual,pred,vres,margin_grid)
report['synthetic_total_threshold_tests']=binary_eval(total_actual,total_pred,total_res,total_grid)
report['distribution_warning']='Thresholds are synthetic calibration diagnostics from 2024 only; NOT sportsbook lines and cannot estimate positive EV or ROI.'
# Serialize fit coefficients and scope metadata for reproducibility;
# not deployable for 2026 without rolling updates and audit.
with open('results/model_coefficients.json','w') as f:
    json.dump({'margin_coefs':model.coef_.tolist(),'margin_intercept':float(model.intercept_),
               'total_coefs':total_model.coef_.tolist(),'total_intercept':float(total_model.intercept_),
               'feature_columns':['home_for','home_against','away_for','away_against','elo_diff','home_games','away_games'],
               'training_years':'2016-2023','calibration_year':2024,'test_year':2025,
               'research_only':True},f,indent=2)
with open('results/report.json','w') as f:json.dump(report,f,indent=2)
print(json.dumps(report,indent=2))
