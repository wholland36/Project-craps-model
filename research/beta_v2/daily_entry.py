"""Additive operational staging and roundoff-only grading; frozen engines unchanged."""
import argparse,fcntl,json,math,hashlib
from pathlib import Path
from datetime import datetime,timezone
import requests
from . import runtime
from research import beta_daily

TOL=1e-10
POLICY='roundoff-only-grading-v1-20261106'
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def numeric_masses(p):
 p=list(map(float,p))
 if len(p)!=3 or any(not math.isfinite(x) for x in p) or min(p)<-TOL or max(p)>1+TOL or abs(sum(p)-1)>TOL:raise ValueError('materially invalid probability vector')
 q=[min(1.,max(0.,x)) for x in p];total=sum(q)
 if total<=0:raise ValueError('empty probability vector')
 return [x/total for x in q]

def check_entry():
 p=runtime.STATE/'daily-entry-manifest.json'
 m=json.loads(p.read_text())
 if m['sha256']!=digest(__file__):raise ValueError('daily entry code drift')
 runtime.algorithm_check(runtime.STATE)

def stage_current(stage):
 folder=stage/'data/current-ncaab';folder.mkdir(parents=True,exist_ok=False);receipts=[]
 for kind,tag,name in [('schedule','espn_mens_college_basketball_schedules','mbb_schedule_2027.parquet'),('box','espn_mens_college_basketball_team_boxscores','team_box_2027.parquet')]:
  url='https://github.com/sportsdataverse/sportsdataverse-data/releases/download/'+tag+'/'+name
  r=requests.get(url,timeout=60);r.raise_for_status();p=folder/(kind+'-2027.parquet');p.write_bytes(r.content);p.chmod(0o600)
  receipts.append(dict(url=url,path=str(p),sha256=digest(p),observed_at=datetime.now(timezone.utc).isoformat(),original_publication_at=None,independently_authenticated=False))
 runtime.dump(folder/'receipts.json',dict(sources=receipts))

def prepare(state,output):
 date=runtime.clock().astimezone(runtime.ZoneInfo('America/New_York')).date().isoformat();receipt=state/'preparations'/(date+'.json')
 if receipt.exists():return json.loads(receipt.read_text())
 # Existing interrupted stages remain intact for audit. Never overwrite or reuse a failed fit.
 stage=state/'builds'/(date+'-staged-v1')
 if stage.exists():raise ValueError('staged preparation incomplete; audit before another attempt')
 stage_current(stage)
 from .training import run
 from .calibration import build
 run(stage,output/'training'/date/'staged-v1');build(stage,output/'calibration'/date/'staged-v1');result=runtime.freeze_bundle(state,stage)
 result.update(operational_policy=POLICY,current_inputs_staged=True,failed_prior_stage_preserved=(state/'builds'/date).exists())
 runtime.dump(receipt,result);return result

def run_v1(output):
 state=beta_daily.DEFAULT_STATE;adjustments=[];old_score=beta_daily.proper_scores;old_settle=beta_daily.settle
 def score(p,outcome):
  q=numeric_masses(p)
  if list(p)!=q:adjustments.append(dict(original=list(p),derived=q))
  return old_score(q,outcome)
 def settle(record,event):
  g=old_settle(record,event)
  if g:g['grading_numeric_policy']=POLICY
  return g
 beta_daily.proper_scores=score;beta_daily.settle=settle
 try:
  with (state/'run.lock').open('a') as f:
   fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);result=beta_daily.run(state,output,collect_availability=True)
 finally:beta_daily.proper_scores=old_score;beta_daily.settle=old_settle
 runtime.dump(runtime.STATE/'maintenance'/(runtime.clock().strftime('%Y%m%dT%H%M%S%fZ')+'-v1-grading.json'),dict(policy=POLICY,adjustments=adjustments,frozen_forecasts_edited=False,note='Derived grading only; deviations beyond1e-10 rejected; no tail smoothing or model change'))
 return result

def main():
 p=argparse.ArgumentParser();p.add_argument('--output',required=True,type=Path);p.add_argument('--prepare',action='store_true');p.add_argument('--v1',action='store_true');a=p.parse_args();check_entry();a.output.mkdir(parents=True,exist_ok=True)
 if a.v1:result=run_v1(a.output);print(json.dumps({k:result[k] for k in ['source_errors','new_forecasts','paid_requests','official_mutations'] if k in result}));return
 with (runtime.STATE/'run.lock').open('a') as f:
  fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
  if a.prepare:prepare(runtime.STATE,a.output)
  result=runtime.run(runtime.STATE,a.output,True)
 print(json.dumps({k:result[k] for k in ['new_forecasts','source_errors','quarantines','journal_anchor']},indent=2))
if __name__=='__main__':main()
