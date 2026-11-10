"""New pregame comparisons, never backfilled into original pilot forecasts."""
import argparse,copy,hashlib,json,math
from pathlib import Path
from collections import defaultdict,Counter
from research.three_sport_validation import read,create,sha,verify,append,now,instant,forecast,masses,score,SPORTS
from research.beta_daily import official_check
from research.beta_v2 import benchmarks
from research.market_audit import settlement
from project_craps.features import update,vector
from project_craps.model import predict,score_distribution,outcome_masses

def independent_elo(history,events,asof):
 """Same fixed K20/HFA55 Elo as development; all results embargoed24h."""
 ratings=defaultdict(lambda:1500.);pending=[];cut=instant(asof)
 for r in sorted(history,key=lambda r:(instant(r['kickoff']),r['event_id'])):
  if instant(r['result_observed_at'])>=cut:continue
  t=instant(r['kickoff'])
  for v in [v for v in pending if instant(v['result_observed_at'])<t]:
   delta=20*(v['_y']-v['_p']);ratings[v['home_id']]+=delta;ratings[v['away_id']]-=delta
  pending=[v for v in pending if instant(v['result_observed_at'])>=t]
  p=1/(1+10**(-(ratings[r['home_id']]-ratings[r['away_id']]+(0 if r['neutral'] else 55))/400))
  pending.append(dict(r,_p=p,_y=1 if r['home_score']>r['away_score'] else .5 if r['home_score']==r['away_score'] else 0))
 for v in pending:
  delta=20*(v['_y']-v['_p']);ratings[v['home_id']]+=delta;ratings[v['away_id']]-=delta
 return {e['event_id']:1/(1+10**(-(ratings[e['home_id']]-ratings[e['away_id']]+(0 if e['neutral'] else 55))/400)) for e in events if instant(e['kickoff'])>cut}

def official_football(sport,events,history,asof):
 pointer,_=official_check();binding=pointer['sports'][sport];m=read(binding['path']);m=m.get('payload',m);st=copy.deepcopy(m['state']);cut=instant(asof)
 for r in sorted(history,key=lambda r:(instant(r['kickoff']),r['event_id'])):
  if instant(r['kickoff'])<=instant(m['state_through']) or instant(r['result_observed_at'])>=cut:continue
  update(st,dict(r,sport=sport))
 result={}
 for e in events:
  x=vector(st,dict(e,sport=sport));means=predict(m,x)
  result[e['event_id']]=dict(scores=score_distribution(m,x),point_margin=means[0],point_total=means[1],official_winner_probability=None,official_model_sha256=binding['sha256'],feature_asof=asof,status='NEW_EXECUTED_RESEARCH_REFERENCE_NOT_ORIGINAL_BETTING_PROBABILITY')
 return result

def run(state,output,register=False):
 from research.beta_v2.runtime import STATE,load_bundle
 import fcntl
 state=Path(state);verify(state);pointer,_=official_check()
 # Imported official football numerical code must be byte-identical to release.
 release=read(pointer['active_release_manifest']);root=Path(pointer['active_release_manifest']).parent
 for f in ['project_craps/features.py','project_craps/model.py']:
  if sha(Path(f))!=release['code_sha256'][str(root/'source'/f)]:raise ValueError('official execution code drift')
 reg=state/'comparator-registration-v3.json'
 code=[Path(__file__),Path(benchmarks.__file__),Path('project_craps/features.py'),Path('project_craps/model.py')]
 if not reg.exists():
  if not register:raise ValueError('comparator registration missing; routine registration prohibited')
  create(reg,dict(registered_at=now().isoformat(),files={str(p.resolve()):sha(p) for p in code},elo=dict(K=20,HFA=55),parent_artifacts_sha256=sha(state/'artifacts.json'),cohort='NEW_PREGAME_DESCRIPTIVE_COMPARISONS_EXCLUDED_FROM_CONFIRMATION',maintenance='preserve earlier comparisons; append newly captured book/line pairs and grade each comparison vintage; repeated vintages are not new games'))
 registration=read(reg)
 for p,h in registration['files'].items():
  if sha(p)!=h:raise ValueError('comparator code drift')
 if sha(state/'artifacts.json')!=registration['parent_artifacts_sha256']:raise ValueError('comparator parent drift')
 captured=now();new=Counter();fail=[]
 with (state/'run.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  append(state,'receipts',dict(at=captured.isoformat(),kind='comparison_check'))
  old=[read(p) for p in (state/'comparisons').glob('*.json')] if (state/'comparisons').exists() else []
  seen={(r['sport'],r['event_id']) for r in old}
  def qkey(s,e,q):return (s,e,q['book_id'],q['market'],q['line'])
  paired_keys={qkey(r['sport'],r['event_id'],p['quote']) for r in old for p in r['pairs']}
  quarantined={(read(p)['sport'],read(p)['event_id']) for p in (state/'quarantines').glob('*.json')}
  ff=[read(p) for p in (state/'forecasts').glob('*.json')]
  qq=[read(p) for p in (state/'quotes').glob('*.json')]
  folder,_,_=load_bundle(STATE)
  for sport in SPORTS:
   try:
    needs_pairs={q['event_id'] for q in qq if q['sport']==sport and qkey(sport,q['event_id'],q['quote']) not in paired_keys and (captured-instant(q['issued_at'])).total_seconds()<=3600}
    records=[r for r in ff if r['sport']==sport and (sport,r['event_id']) not in quarantined and ((sport,r['event_id']) not in seen or r['event_id'] in needs_pairs) and instant(r['identity']['kickoff'])>captured and r['forecast'].get('arms')]
    if not records:continue
    events=[r['identity'] for r in records];history=read(state/sport/'history.json');model=read(state/sport/'model.json')
    ep=independent_elo(history,events,captured.isoformat())
    refs=benchmarks.ncaab(events,captured.isoformat(),folder/'data/current-ncaab') if sport=='NCAAB' else official_football(sport,events,history,captured.isoformat())
    for r in records:
     e=r['identity'];ref=refs.get(r['event_id'],dict(status='MISSING'))
     if instant(e['kickoff'])<=now():continue
     f=forecast(model,e,now().isoformat());cm={}
     for arm,c in f.get('arms',{}).items():cm[arm]=masses(c,sport,'moneyline','home')
     if ref.get('scores'):cm['official_score_reference']=list(outcome_masses(ref['scores'],'moneyline','home',None,tie_policy='refund'))
     pairs=[]
     for q in qq:
      if (q['sport'],q['event_id'])!=(sport,r['event_id']):continue
      if qkey(sport,r['event_id'],q['quote']) in paired_keys:continue
      if (captured-instant(q['issued_at'])).total_seconds()>3600:continue
      a=q['quote'];ps={arm:masses(c,sport,a['market'],a['selection'],a['line']) for arm,c in f.get('arms',{}).items()}
      if ref.get('scores'):ps['official_score_reference']=list(outcome_masses(ref['scores'],a['market'],a['selection'],a['line'],tie_policy='refund' if a['market']=='moneyline' else None))
      pairs.append(dict(quote=a,quote_observed_at=q['issued_at'],probabilities=ps))
     append(state,'comparisons',dict(sport=sport,event_id=r['event_id'],identity=e,issued_at=now().isoformat(),winner_masses=cm,official_exact_winner_probability=ref.get('official_winner_probability'),official_status=ref.get('status'),official_model_sha256=pointer['sports'][sport]['sha256'],elo_probability=ep.get(r['event_id']),elo_history_sha256=sha(state/sport/'history.json'),pairs=pairs,original_first_forecast_sha256=hashlib.sha256(json.dumps(r,sort_keys=True,separators=(',',':')).encode()).hexdigest(),new_inference=True,old_feature_cutoff=f.get('feature_cutoff'),source_timing_authenticated=False,approved_risk=0));new[sport]+=1
   except Exception as e:fail.append(dict(sport=sport,error=str(e)))
  # Grade only comparisons actually issued before kickoff; never backfill a missing arm.
  comps=[read(p) for p in (state/'comparisons').glob('*.json')]
  prior={read(p)['comparison_sha256'] for p in (state/'comparison_grades').glob('*.json')} if (state/'comparison_grades').exists() else set()
  finals={(read(p)['sport'],read(p)['event_id']):read(p) for p in (state/'grades').glob('*.json')} if (state/'grades').exists() else {}
  for c in comps:
   key=(c['sport'],c['event_id'])
   cid=hashlib.sha256(json.dumps(c,sort_keys=True,separators=(',',':')).encode()).hexdigest()
   if cid in prior or key in quarantined or key not in finals:continue
   if instant(c['issued_at'])>=instant(c['identity']['kickoff']):raise ValueError('late comparator')
   hs,aws=finals[key]['scores'];y=1 if hs>aws else 0 if hs==aws else -1
   gs={a:score(p,y) for a,p in c['winner_masses'].items()}
   append(state,'comparison_grades',dict(sport=c['sport'],event_id=c['event_id'],comparison_sha256=cid,winner_grades=gs,elo_brier=None if y==0 else (c['elo_probability']-(y==1))**2,exact_official_winner_brier=None if y==0 or c['official_exact_winner_probability'] is None else (c['official_exact_winner_probability']-(y==1))**2,observed_at=now().isoformat(),approved_risk=0));new['grades']+=1
  result=dict(asof=now().isoformat(),new=dict(new),failures=fail,approved_risk=0,confirmation_open=False)
  create(output,result);return result

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--state',required=True);p.add_argument('--output',required=True);p.add_argument('--register',action='store_true');a=p.parse_args();print(json.dumps(run(a.state,a.output,a.register),indent=2))
