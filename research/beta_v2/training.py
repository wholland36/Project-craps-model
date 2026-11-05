"""Local normalized, audited strength builds. Never changes beta v1."""
import csv,json,hashlib,math
from pathlib import Path
from datetime import datetime,timedelta,timezone
from collections import Counter
import numpy as np
from .strength import fit,predict,point,instant,boolean,VERSION
CENTRAL=Path('/Users/wadeholland/Documents/Codex/Project-Craps')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,x):p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,indent=2,allow_nan=False)+'\n')
def join_box(schedule,boxes):
 if len(boxes)!=2:raise ValueError('not_exactly_two_box_rows')
 ids={str(int(x['team_id'])) for x in boxes};expected={schedule['home_id'],schedule['away_id']}
 if len(ids)!=2 or ids!=expected:raise ValueError('participant_mismatch')
 vals=[]
 for b in boxes:
  team=str(int(b['team_id']));other=next(t for t in ids if t!=team)
  if str(int(b['opponent_team_id']))!=other:raise ValueError('opponent_mismatch')
  expected_score=schedule['home_score'] if team==schedule['home_id'] else schedule['away_score']
  if float(b['team_score'])!=expected_score:raise ValueError('score_mismatch')
  q=[float(b[k]) for k in ['field_goals_attempted','free_throws_attempted','offensive_rebounds','turnovers']]
  if not all(math.isfinite(v) and v>=0 for v in q):raise ValueError('invalid_box_counter')
  vals.append(q[0]+.44*q[1]-q[2]+q[3])
 if min(vals)<=0 or abs(vals[0]-vals[1])>12:raise ValueError('possession_disagreement')
 return sum(vals)/2

def build(state):
 import pandas as pd
 state=Path(state);now=datetime.now(timezone.utc);rows={'NFL':[],'NCAAB':[]};excluded=[];sources=[];seen=set()
 def append(sport,r):
  key=(sport,r['event_id'])
  if key in seen:raise ValueError('duplicate_event')
  seen.add(key)
  if instant(r['result_observed_at'])>=now:raise ValueError('not_known_before_capture')
  if not all(math.isfinite(r[k]) and r[k]>=0 for k in ['home_score','away_score']):raise ValueError('invalid_scores')
  if r['home_id']==r['away_id']:raise ValueError('same_participant')
  r.update(source_capture_at=now.isoformat(),availability_time_basis='RECONSTRUCTED_24H_EMBARGO_NOT_ORIGINAL_OBSERVATION',original_result_observed_at=None)
  rows[sport].append(r)
 nfl=CENTRAL/'state/research-extensions/daily-challengers-v1-20261105/efficiency/nflverse-games.csv';sources.append({'path':str(nfl),'sha256':sha(nfl)})
 for x in csv.DictReader(nfl.open()):
  if int(x['season'])<2023:continue
  try:
   if not x['home_score'] or not x['away_score']:raise ValueError('not_final_score')
   # NFL source gametime is US Eastern; zoneinfo handles DST.
   from zoneinfo import ZoneInfo
   t=datetime.fromisoformat(x['gameday']+'T'+x['gametime']).replace(tzinfo=ZoneInfo('America/New_York')).astimezone(timezone.utc)
   r=dict(event_id=x['game_id'],kickoff=t.isoformat(),result_observed_at=(t+timedelta(hours=24)).isoformat(),season=int(x['season']),home_id=x['home_team'],away_id=x['away_team'],home_score=float(x['home_score']),away_score=float(x['away_score']),neutral=x['location']=='Neutral',final=True,sport='NFL',result_time_basis='assumed kickoff+24h retrospective; not source receipt',source_sha256=sources[-1]['sha256'])
   append('NFL',r)
  except (ValueError,TypeError) as e:excluded.append({'sport':'NFL','event_id':x['game_id'],'reason':str(e)})
 base=CENTRAL/'releases/2026-11-03-v1/data/NCAAB'
 paths=[(base/f'schedule-{y}.parquet',base/f'box-{y}.parquet') for y in [2024,2025,2026]]
 paths.append((state/'data/current-ncaab/schedule-2027.parquet',state/'data/current-ncaab/box-2027.parquet'))
 # A newer cached season is admitted only with a paired schedule and box file.
 for sp,bp in paths:
  if not sp.exists() or not bp.exists():
   excluded.append({'sport':'NCAAB','event_id':None,'reason':'paired_season_files_unavailable','season_file':sp.name});continue
  if sp.parent==base:
   released=json.loads((base/'manifest.json').read_text())['files']
   for source_path in (sp,bp):
    if sha(source_path)!=released[source_path.name]['SHA256']:raise ValueError('released_source_hash_mismatch')
  sources.extend([{'path':str(p),'sha256':sha(p)} for p in (sp,bp)])
  ss=pd.read_parquet(sp);bs=pd.read_parquet(bp);groups={str(int(g)):v.to_dict('records') for g,v in bs.groupby('game_id')}
  for x in ss.to_dict('records'):
   gid=str(int(x['game_id']))
   try:
    if not boolean(x['status_type_completed']):raise ValueError('not_final')
    if not boolean(x['time_valid']):raise ValueError('unverified_kickoff')
    t=instant(x['date']);periods=float(x['status_period'])
    if not math.isfinite(periods) or periods<2 or periods!=int(periods):raise ValueError('invalid_periods')
    r=dict(event_id=gid,kickoff=t.isoformat(),result_observed_at=(t+timedelta(hours=24)).isoformat(),season=int(x['season']),home_id=str(int(x['home_id'])),away_id=str(int(x['away_id'])),home_score=float(x['home_score']),away_score=float(x['away_score']),neutral=boolean(x['neutral_site']),final=True,sport='NCAAB',minutes=40+5*(int(periods)-2),result_time_basis='assumed kickoff+24h retrospective; not source receipt',source_sha256=sources[-2]['sha256'])
    r['possessions']=join_box(r,groups.get(gid,[]));append('NCAAB',r)
   except (ValueError,TypeError,KeyError) as e:excluded.append({'sport':'NCAAB','event_id':gid,'reason':str(e)})
 for sport,rr in rows.items():rr.sort(key=lambda r:(instant(r['kickoff']),r['event_id']));save(state/'data'/(sport+'-normalized.json'),rr)
 save(state/'data/source-manifest.json',dict(captured_at=now.isoformat(),sources=sources,counts={s:len(r) for s,r in rows.items()},exclusions=dict(Counter(x['reason'] for x in excluded)),authentication='retrospective snapshots; assumed result lag not original publication'))
 save(state/'data/excluded-retained.json',excluded)
 return rows

def metrics(rr):
 if not rr:return {}
 return dict(n=len(rr),margin_mae=float(np.mean([abs(r['home_score']-r['away_score']-r['predicted_margin']) for r in rr])),total_mae=float(np.mean([abs(r['home_score']+r['away_score']-r['predicted_total']) for r in rr])),winner_brier=float(np.mean([(sum(h>a for h,a in r['scores'])/len(r['scores'])-float(r['home_score']>r['away_score']))**2 for r in rr])),interpretation='chronological development only; pooled home-winner Brier includes NFL ties as non-home win; no market comparison available')

def run(state,output):
 state=Path(state);output=Path(output);rows=build(state);report={};cutoff=datetime.now(timezone.utc).isoformat();code_sha=sha(Path(__file__).with_name('strength.py'))
 for sport,rr in rows.items():
  periods=sorted({(instant(r['kickoff']).year,(instant(r['kickoff']).month-1)//3) for r in rr});oof=[];priorres=[];folds=[]
  for year,q in periods:
   origin=datetime(year,1+3*q,1,tzinfo=timezone.utc);end=datetime(year+1,1,1,tzinfo=timezone.utc) if q==3 else datetime(year,4+3*q,1,tzinfo=timezone.utc)
   train=[r for r in rr if instant(r['result_observed_at'])<origin];test=[r for r in rr if origin<=instant(r['kickoff'])<end]
   if len(train)<100 or not test:continue
   model=fit(train,sport=sport,cutoff=(origin-timedelta(microseconds=1)).isoformat(),residuals=priorres[-128:])
   if not priorres:
    # First fold warms OOF residual archive only; excluded from calibration/test OOF.
    for r in test:
     p=point(model,r)
     if p and instant(r['result_observed_at'])<end:priorres.append([r['home_score']-p[0],r['away_score']-p[1]])
    folds.append({'origin':origin.isoformat(),'train_n':len(train),'warmup':True});continue
   pending=[]
   for r in test:
    p=predict(model,r)
    if p['status']!='RESEARCH_ONLY' or not p['paired_score_samples']:continue
    h,a=p['point_scores'];row={k:r[k] for k in ['event_id','kickoff','result_observed_at','home_score','away_score','sport','result_time_basis','availability_time_basis','original_result_observed_at','source_capture_at']};row.update(predicted_margin=h-a,predicted_home_margin=h-a,predicted_total=h+a,scores=p['paired_score_samples'],parent_train_cutoff=model['cutoff'],parent_family=VERSION,parent_code_sha256=code_sha,home_id=r['home_id'],away_id=r['away_id']);oof.append(row)
    if instant(r['result_observed_at'])<end:pending.append([r['home_score']-h,r['away_score']-a])
   priorres.extend(pending);folds.append({'origin':origin.isoformat(),'train_n':len(train),'oof_n':len(pending),'warmup':False})
  final=fit(rr,sport=sport,cutoff=cutoff,residuals=priorres[-512:]);final['code_sha256']=code_sha;final['residual_scope']='strictly prior quarter-origin OOF forecast errors; 512 latest';save(state/'strength'/(sport+'.json'),final)
  save(state/'data'/(sport+'-oof.json'),oof);report[sport]=dict(final_train_n=final['train_n'],train_last=final['train_last'],model_sha256=sha(state/'strength'/(sport+'.json')),oof_n=len(oof),folds=folds,development_2026=metrics([r for r in oof if instant(r['kickoff']).year==2026]),earlier_calibration=metrics([r for r in oof if instant(r['kickoff']).year<2026]),limitations=['Not untouched confirmation: historical sources/results already inspected','Result availability is assumed24h, not authenticated publication','NFL no drive inputs: explicit full-score fallback','NCAAB2027 paired box/schedule unavailable if excluded; fresh2026-27 player strength not fabricated','OT mean adjustment empirical; no validated game-specific OT mechanism','Final refreshed strength and OOF folds have different weights; calibration transfer remains research'])
 save(output/'strength-report.json',report)
 return report
if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('--state',required=True);p.add_argument('--output',required=True);a=p.parse_args();print(json.dumps(run(a.state,a.output),indent=2))
