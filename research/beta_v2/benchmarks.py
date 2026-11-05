"""Fresh research inference using exact frozen official coefficients and code.

Never modifies official first forecasts; no probabilities are backfilled into them.
"""
import copy,hashlib,importlib.util,json,math
from datetime import timedelta
from pathlib import Path
import numpy as np
from scipy.special import expit
from project_craps.common import instant
from project_craps.features import update,vector
from project_craps.model import predict,score_distribution
from research.beta_daily import official_check

CENTRAL=Path('/Users/wadeholland/Documents/Codex/Project-Craps')

def nfl_alias(team):return {'LAR':'LA','WSH':'WAS'}.get(str(team),str(team))

def nfl(events,rows,asof):
 p,_=official_check();binding=p['sports']['NFL'];wrapped=json.loads(Path(binding['path']).read_text());m=wrapped.get('payload',wrapped);state=copy.deepcopy(m['state']);cut=instant(asof)
 for r in sorted(rows,key=lambda r:(instant(r['kickoff']),r['event_id'])):
  if instant(r['kickoff'])<=instant(m['state_through']):continue
  if instant(r['result_observed_at'])>cut or instant(r['kickoff'])>=cut:continue
  g=dict(r,sport='NFL',home_id=nfl_alias(r['home_id']),away_id=nfl_alias(r['away_id']));update(state,g)
 out={}
 for event in events:
  e=dict(event,sport='NFL',home_id=nfl_alias(event['home_id']),away_id=nfl_alias(event['away_id']))
  if instant(e['kickoff'])<=cut:continue
  x=vector(state,e);means=predict(m,x);scores=score_distribution(m,x);elo=1/(1+10**(-x[4]/400))
  out[str(e['event_id'])]=dict(status='COMPUTED_NEW_RESEARCH_REFERENCE',point_margin=means[0],point_total=means[1],scores=scores,official_model_sha256=binding['sha256'],feature_sha256=hashlib.sha256(np.asarray(x).tobytes()).hexdigest(),feature_asof=asof,independent_elo=elo,official_winner_probability=None,winner_note='NFL official score-distribution model; no separate logistic comparator',source_limit='Historical result availability reconstructed with embargo; not original receipt',new_inference_not_original_forecast=True)
 return out

def _engine():
 path=CENTRAL/'releases/2026-11-03-v1/source/ncaab_research/engine.py';spec=importlib.util.spec_from_file_location('beta_v2_verified_official_ncaab_engine',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def ncaab(events,asof,current_dir):
 p,_=official_check();binding=p['sports']['NCAAB'];m=json.loads(Path(binding['path']).read_text());m=m.get('payload',m);data=CENTRAL/'releases/2026-11-03-v1/data/NCAAB';cur=Path(current_dir)
 if not (cur/'schedule-2027.parquet').exists() or not (cur/'box-2027.parquet').exists():
  return {str(e['event_id']):dict(status='CURRENT_SCHEDULE_BOX_INPUTS_MISSING') for e in events}
 manifest=json.loads((data/'manifest.json').read_text())
 for kind in ['schedule','box']:
  for year in range(2016,2027):
   name=f'{kind}-{year}.parquet'
   if hashlib.sha256((data/name).read_bytes()).hexdigest()!=manifest['files'][name]['SHA256']:raise ValueError('canonical basketball input changed: '+name)
 engine=_engine();games,stats,issues=engine.read('ncaam',[data/f'schedule-{y}.parquet' for y in range(2016,2027)]+[cur/'schedule-2027.parquet'],[data/f'box-{y}.parquet' for y in range(2016,2027)]+[cur/'box-2027.parquet'])
 cut=instant(asof);capped=[dict(g,completed=False) if g['time']+timedelta(hours=24)>cut else dict(g) for g in games]
 X,audits=engine.features(capped,stats,'ncaam');byid={g['game_id']:(i,g) for i,g in enumerate(games)};out={}
 for event in events:
  eid=str(event['event_id']);pair=byid.get(eid)
  if pair is None:out[eid]=dict(status='OUTSIDE_VERIFIED_OFFICIAL_D1_SCHEDULE',eligibility='unknown_or_non_division1');continue
  i,g=pair
  if (g['home'],g['away'],g['time'])!=(str(event['home_id']),str(event['away_id']),instant(event['kickoff'])):
   out[eid]=dict(status='SCHEDULE_IDENTITY_KICKOFF_MISMATCH');continue
  if cut>=g['time']:out[eid]=dict(status='ALREADY_STARTED');continue
  if instant(audits[i]['latest_history_kickoff_UTC'])+timedelta(hours=24)>cut:raise ValueError('official source embargo failed')
  x=X[i:i+1];pm=float(engine.linear(m['models']['margin'],x)[0]);pt=float(engine.linear(m['models']['total'],x)[0]);raw=float(engine.linear(m['models']['win'],x)[0]);winner=float(expit(m['calibration']['slope']*raw+m['calibration']['intercept']))
  scores=[]
  for dm,dt in m['residual_pairs']:
   h=max(0,math.floor((pt+dt+pm+dm)/2+.5));a=max(0,math.floor((pt+dt-pm-dm)/2+.5))
   if h!=a:scores.append((h,a))
  out[eid]=dict(status='COMPUTED_NEW_RESEARCH_REFERENCE',point_margin=pm,point_total=pt,scores=scores,official_model_sha256=binding['sha256'],official_winner_probability=winner,official_logistic_raw=raw,independent_elo=audits[i]['elo_probability'],feature_sha256=hashlib.sha256(x.tobytes()).hexdigest(),feature_asof=asof,history_audit=audits[i],eligibility='source_D1_schedule_flags_verified; independent_certification_unresolved',new_inference_not_original_forecast=True)
 return out
