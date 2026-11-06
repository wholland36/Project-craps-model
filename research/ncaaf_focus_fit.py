import json,pathlib,sys,math
import numpy as np
from scipy.optimize import minimize
sys.path.insert(0,str(pathlib.Path.cwd()))
from research.ncaaf_focus import ROOT,exclusive,canonical,sha
from research.market_audit import checked
from research.beta_daily import official_check
pointer,_=official_check()
private=pathlib.Path('/Users/wadeholland/Documents/Codex/Project-Craps/state/odds-history/ncaaf-20261105-v1')
rows=[];counts={}
for line in (private/'joined-retrospective-quotes.jsonl').open():
 q=json.loads(line)
 if q['season'] not in [2022,2023] or q['market']!='spread' or q['selection']!='home':continue
 r=checked(q)
 if r['outcome']:
  rows.append((q['event_id'],r['model_conditional_win'],int(r['outcome']==1)));counts[q['event_id']]=counts.get(q['event_id'],0)+1
x=np.array([math.log(max(1e-12,min(1-1e-12,r[1]))/(1-max(1e-12,min(1-1e-12,r[1])))) for r in rows]);y=np.array([r[2] for r in rows]);w=np.array([1/counts[r[0]] for r in rows])
def objective(b):
 z=b[0]+b[1]*x;return float(np.sum(w*(np.logaddexp(0,z)-y*z))+.5*b[1]**2)
f=minimize(objective,[0,1],method='L-BFGS-B',bounds=[(None,None),(0,None)])
assert f.success
art=dict(version='ncaaf-five-game-challengers-v1',frozen_at=__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),parent_model_sha256=pointer['sports']['NCAAF']['sha256'],spread=dict(intercept=float(f.x[0]),slope=float(f.x[1]),training_seasons=[2022,2023],event_count=len(counts),fit='event-weighted binary logistic, slope>=0, slope ridge1, no grid',training_input_sha256=sha((private/'joined-retrospective-quotes.jsonl').read_bytes()),transport_limit='historical architecture fold calibrator applied to current first-mean point kernel; new prospective transport test, not validated calibration'),total=dict(market_blend_weight=.5,model_blend_weight=.5,push='model push retained; bookmaker conditional probability is not a push estimate'),rejected_unconstrained_spread_slope=-.1896171942088207,cohort='EXPLORATORY_FORWARD_SHADOW',real_risk=0)
exclusive(ROOT/'challengers.json',canonical(art));exclusive(ROOT/'manifest.json',canonical(dict(artifact_sha256=sha((ROOT/'challengers.json').read_bytes()),code_sha256=sha(pathlib.Path('research/ncaaf_focus.py').read_bytes()),confirmation=False)))
print(json.dumps(art,indent=2))
