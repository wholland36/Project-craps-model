import sys,json,pathlib,collections,math
import numpy as np
from sklearn.linear_model import LogisticRegression
sys.path.insert(0,str(pathlib.Path.cwd()))
from research.market_audit import checked
p=pathlib.Path('/Users/wadeholland/Documents/Codex/Project-Craps/state/odds-history/ncaaf-20261105-v1/joined-retrospective-quotes.jsonl')
out=pathlib.Path('../../outputs/ncaaf-next-20261106');out.mkdir(exist_ok=True)
groups=collections.defaultdict(list)
for line in p.open():
 q=json.loads(line);r=checked(q)
 if r['outcome']:groups[(q['season'],q['market'],q['event_id'])].append((r['model_conditional_win'],r['no_vig_conditional_win'],int(r['outcome']==1),q['selection']))
results=[]
for market in ['moneyline','spread','total']:
 train=[];test=[];weights=[];tw=[]
 for (year,m,gid),rows in groups.items():
  if m!=market:continue
  # Keep home/over side only to avoid complementary-label double counting.
  rows=[r for r in rows if r[3] in ['home','over']]
  if not rows:continue
  target=train if year<=2023 else test;w=weights if year<=2023 else tw
  for a,b,y,_ in rows:target.append((a,b,y));w.append(1/len(rows))
 train=np.array(train);test=np.array(test);tw=np.array(tw);weights=np.array(weights)
 def logit(x):return np.log(np.maximum(x,1e-12)/np.maximum(1-x,1e-12))
 model=LogisticRegression(C=1.,solver='lbfgs',max_iter=1000)
 model.fit(logit(train[:,0]).reshape(-1,1),train[:,2],sample_weight=weights)
 cal=model.predict_proba(logit(test[:,0]).reshape(-1,1))[:,1]
 blend=.5*test[:,0]+.5*test[:,1]
 brier=lambda v:float(np.average((v-test[:,2])**2,weights=tw))
 bins=[]
 for lo in np.arange(0,1,.1):
  ix=(test[:,0]>=lo)&(test[:,0]<lo+.1)
  if ix.any():bins.append(dict(lower=float(lo),rows=int(ix.sum()),effective_game_weight=float(tw[ix].sum()),mean_model=float(np.average(test[ix,0],weights=tw[ix])),observed_rate=float(np.average(test[ix,2],weights=tw[ix]))))
 results.append(dict(market=market,fit_seasons=[2022,2023],examined_diagnostic_seasons=[2024,2025],test_rows=len(test),game_weight=float(tw.sum()),brier=dict(model=brier(test[:,0]),market=brier(test[:,1]),recalibrated=brier(cal),fixed_half_market_blend=brier(blend)),logistic_intercept=float(model.intercept_[0]),logistic_slope=float(model.coef_[0,0]),reliability_bins=bins))
(out/'development-diagnostics.json').write_text(json.dumps(dict(scope='EXAMINED DEVELOPMENT ONLY; exploratory; no untouched tests, no model promotion',weighting='one home/over side, each event equal weight within market',results=results),indent=2)+'\n')
s='# NCAA football development diagnosis — November 6\n\nExploratory development only. Calibrator fitted on 2022–2023; assessed on already examined 2024–2025. No untouched test or prospective improvement claim. Each game receives equal total weight per market; one side only avoids complementary-label duplication. Inputs are retrospective and source authentication remains incomplete.\n\n|Market|Original Brier|Sportsbook Brier|Recalibrated Brier|50/50 market blend Brier|\n|---|---:|---:|---:|---:|\n'
for r in results:
 b=r['brier'];s+=f"|{r['market']}|{b['model']:.5f}|{b['market']:.5f}|{b['recalibrated']:.5f}|{b['fixed_half_market_blend']:.5f}|\n"
s+='\nThe logistic recalibrator uses logit(model probability), an intercept and slope. Endpoint clipping is used only as a finite feature transform in this exploratory fit, never to conceal logloss or modify frozen probabilities. A 50/50 blend is a market-informed comparator, not independent evidence. No production coefficients were replaced.\n\nNext work: prioritize probability calibration if reliability bins show overconfidence, then investigate conditional margin/total residuals on earlier development data. Test any chosen challenger on new future games; do not select it using this examined diagnostic and call the result confirmation. No injury/trap/momentum improvement is established by these tests. These fits do not estimate player value or authenticate QB, weather or AP poll timing.\n'
(out/'DEVELOPMENT_DIAGNOSIS.md').write_text(s);print(json.dumps(results,default=str)[:1800])
