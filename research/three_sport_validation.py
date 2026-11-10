"""Separate three-sport development program; no official mutations or paid calls.

One forecast function is used for chronological replay and prospective capture.
All historical availability is reconstructed, never authenticated by a hash.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import fcntl
import numpy as np
from scipy.stats import norm
from research.beta_v2.strength import fit as strength_fit, point, instant
from research.beta_support_v3 import geometric_masses
from research.probability_v2 import proper_scores
from research.market_audit import checked, settlement, metrics, implied

ROOT = Path('/Users/wadeholland/Documents/Codex/Project-Craps')
VERSION = 'three-sport-development-v1-20261110'
SPORTS = ('NFL', 'NCAAF', 'NCAAB')
QUARANTINES = {'401911334','401922210','401917962','401920952','401929356',
 '401924951','401920355','401918053','401919029','401929002','401922249',
 '401925662','401919733','401928833','401929357','401920887','401862818'}
POLICY = dict(version=VERSION, sports=SPORTS, approval='RESEARCH_ONLY',
 update='quarter origins UTC; latest completed results with reconstructed24h embargo',
 ridge=20., residual_ridge=20., minimum_prior_team_games=5,
 residual_limit=512, minimum_prior_oof_residuals=50, tail_weight=.01,
 arms=['score_base','rest_form'], seed=20261110,
 features=['opponent_adjusted_score_strength','NCAAB_prior_regulation_pace',
           'rest_gap_from_prior_eligible_games','prior_five_score_margin_form'],
 missing_features=['verified_QB','player_eligibility','replacement_workload',
  'original_weather_forecast_vintage','original_efficiency_publication_time',
  'drive_or_possession_state_football','verified_starting_lineups'],
 calibration='joint paired OOF score residual distribution, not per-market transforms',
 development='all historical periods examined; no untouched holdout',
 confirmation='CLOSED; all historical and first100 prospective pilot games/sport/market excluded',
 primary='paired conditional Brier vs same-book no-vig; minimum improvement .005',
 family_alpha=.05, hypotheses=9, power=.8,
 confirmation_floor_games=300, confirmation_floor_weeks=12,
 confirmation_design='week-cluster pilot variance and source coverage required before opening; floors are not sufficient sample guarantees',
 selection='rest_form is fixed challenger; score_base is ablation comparator; no winner selection',
 betting='separate executable quote/positive net return test and explicit production authorization',
 real_risk=0, promotion=False)

def canonical(x):
 return json.dumps(x, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p): return json.loads(Path(p).read_text())
def create(p,x):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('xb') as f:f.write(canonical(x))
 p.chmod(0o600)
def now():return datetime.now(timezone.utc)
def code_files():
 return [Path(__file__),Path(__file__).with_name('beta_v2')/'strength.py',
 Path(__file__).with_name('beta_support_v3.py'),Path(__file__).with_name('probability_v2.py'),
 Path(__file__).with_name('market_audit.py')]

def protocol(state):
 from research.beta_daily import official_check
 p,_=official_check();state=Path(state);state.mkdir(parents=True,exist_ok=False)
 create(state/'protocol.json',dict(POLICY,registered_at=now().isoformat(),
  official_parents={s:p['sports'][s]['sha256'] for s in SPORTS}))
 create(state/'code.json',{str(p.resolve()):sha(p) for p in code_files()})

def verify(state,artifacts=True):
 from research.beta_daily import official_check
 p,_=official_check();state=Path(state);pol=read(state/'protocol.json')
 for s,h in pol['official_parents'].items():
  if p['sports'][s]['sha256']!=h:raise ValueError('official parent changed')
 for f,h in read(state/'code.json').items():
  if sha(f)!=h:raise ValueError('registered code drift: '+f)
 if artifacts:
  for f,h in read(state/'artifacts.json').items():
   if sha(state/f)!=h:raise ValueError('registered artifact drift: '+f)
 return pol

def sources():
 from research.beta_v2.runtime import load_bundle,STATE
 folder,_,_=load_bundle(STATE)
 paths={s:folder/'data'/(s+'-normalized.json') for s in ('NFL','NCAAB')}
 paths['NCAAF']=ROOT/'state/odds-history/ncaaf-20261105-v1/source-games/snapshot.json'
 return paths

def load_games(paths):
 from project_craps.common import unwrap
 result={};exclusions=[]
 for sport,p in paths.items():
  obj=read(p);raw=unwrap(obj)['games'] if sport=='NCAAF' else obj
  rows=[];seen=set()
  for original in raw:
   r=dict(original)
   try:
    eid=str(r['event_id'])
    if eid in seen:raise ValueError('duplicate_event')
    seen.add(eid)
    if eid in QUARANTINES:raise ValueError('existing_identity_score_quarantine')
    if sport=='NCAAF':
     if r.get('status')!='FINAL' or not r.get('time_known'):raise ValueError('not_final_or_time_unknown')
     if r['season']<2021:raise ValueError('before_declared_development_start')
     r.update(final=True,result_observed_at=(instant(r['kickoff'])+timedelta(hours=24)).isoformat())
    if not r.get('final'):raise ValueError('not_final')
    for k in ('home_score','away_score'):
     if isinstance(r[k],bool) or not math.isfinite(float(r[k])) or r[k]<0 or r[k]!=int(r[k]):raise ValueError('invalid_score')
    if sport!='NFL' and r['home_score']==r['away_score']:raise ValueError('impossible_full_game_tie')
    if type(r['neutral']) is not bool:raise ValueError('neutral_unknown')
    if not instant(r['kickoff'])<instant(r['result_observed_at'])<now():raise ValueError('invalid_result_availability')
    if r['home_id']==r['away_id']:raise ValueError('same_participant')
    r.update(sport=sport,event_id=eid,availability='RECONSTRUCTED_24H_NOT_AUTHENTICATED')
    rows.append(r)
   except (KeyError,ValueError,TypeError) as e:exclusions.append(dict(sport=sport,event_id=r.get('event_id'),reason=str(e)))
  result[sport]=sorted(rows,key=lambda r:(instant(r['kickoff']),r['event_id']))
 return result,exclusions

def context(rows):
 teams=defaultdict(list);graph=defaultdict(set)
 for r in rows:
  for k,other in [('home_id','away_id'),('away_id','home_id')]:
   t=str(r[k]);m=r['home_score']-r['away_score'];m=m if k=='home_id' else -m
   teams[t].append((r['kickoff'],m));graph[t].add(str(r[other]))
 components={}
 for t in teams:
  if t in components:continue
  stack=[t];cid=t
  while stack:
   u=stack.pop()
   if u in components:continue
   components[u]=cid;stack.extend(graph[u]-components.keys())
 return dict(teams=dict(teams),components=components)

def features(ctx,event):
 h,a=[str(event[k]) for k in ('home_id','away_id')];tt=instant(event['kickoff'])
 rs=[ctx['teams'].get(t,[]) for t in (h,a)]
 reasons=[]
 if min(map(len,rs))<5:reasons.append('insufficient_prior_team_games')
 if ctx['components'].get(h)!=ctx['components'].get(a) or h not in ctx['components']:reasons.append('disconnected_training_components')
 if reasons:return None,reasons
 rest=[min(21.,max(0.,(tt-instant(r[-1][0])).total_seconds()/86400)) for r in rs]
 form=[np.mean([v[1] for v in r[-5:]]) for r in rs]
 return [1.,(rest[0]-rest[1])/7,(form[0]-form[1])/20],[]

def build_model(rows,sport,cutoff,oof):
 train=[r for r in rows if instant(r['result_observed_at'])<instant(cutoff)]
 base=strength_fit(train,sport=sport,cutoff=cutoff,ridge=POLICY['ridge'])
 ctx=context(train);eligible=[r for r in oof if instant(r['result_observed_at'])<instant(cutoff)]
 if len(eligible)<50:return dict(base=base,context=ctx,cutoff=cutoff,sport=sport,status='WARMUP'),train
 # Two-score correction fitted only to earlier issued OOF point errors.
 x=np.asarray([r['features'] for r in eligible]);y=np.asarray([r['errors'] for r in eligible])
 b=np.linalg.solve(x.T@x+np.diag([1.,20.,20.]),x.T@y)
 res=eligible[-POLICY['residual_limit']:]
 # Rest/form residual bank uses prior OOF rest/form forecast errors, not in-sample residuals.
 banks={arm:[r[arm+'_errors'] for r in res if arm+'_errors' in r] for arm in POLICY['arms']}
 return dict(base=base,context=ctx,cutoff=cutoff,sport=sport,status='RESEARCH_ONLY',
  coefficients=b.tolist(),residuals=banks,prior_oof=len(eligible)),train

def forecast(model,event,asof):
 if not instant(model['cutoff'])<=instant(asof)<instant(event['kickoff']):raise ValueError('nonpregame forecast clocks')
 if type(event.get('neutral')) is not bool:raise ValueError('neutral missing')
 f,reasons=features(model['context'],event)
 if reasons:return dict(status='REFUSED',reasons=reasons)
 p=point(model['base'],event)
 if p is None:return dict(status='REFUSED',reasons=['unseen_team'])
 if model['status']=='WARMUP':return dict(status='WARMUP',point=p,features=f)
 adjusted=np.maximum(0,np.asarray(p)+np.asarray(f)@np.asarray(model['coefficients'])).tolist()
 arms={}
 for arm,means in [('score_base',p),('rest_form',adjusted)]:
  bank=model['residuals'][arm]
  if len(bank)<50:continue
  samples=[[max(0,round(means[0]+e[0])),max(0,round(means[1]+e[1]))] for e in bank]
  if model['sport']!='NFL':samples=[s for s in samples if s[0]!=s[1]]
  if not samples:continue
  arms[arm]=dict(point=means,scores=samples,tail_means=[min(250.,max(1.,v)) for v in means])
 return dict(status='RESEARCH_ONLY',features=f,point=p,adjusted=adjusted,arms=arms,
  feature_cutoff=model['cutoff'],current_player_weather_inputs=False,approved_risk=0)

def tail(means,sport,market,side,line):
 if sport!='NFL':return geometric_masses(*means,market,side,line)
 # NFL two-way moneylines refund on a tie. Unconditioned same joint geometric law.
 h,a=[v/(v+1) for v in means];tie=(1-h)*(1-a)/(1-h*a)
 def ge(k,u=h,v=a):return tie*u**k/(1-u) if k>=1 else 1-tie*v**(1-k)/(1-v)
 if market in ('moneyline','spread'):
  th=0. if market=='moneyline' else (-line if side=='home' else line)
  above=ge(math.floor(th)+1);below=ge(1-math.ceil(th),a,h)
  push=tie*(h**int(th) if th>=0 else a**(-int(th))) if float(th).is_integer() else 0.
  win,loss=(above,below) if side=='home' else (below,above)
 else:
  def pmf(n):return (1-h)*(1-a)*sum(h**j*a**(n-j) for j in range(n+1))
  def above(n):return h**(n+1)+(1-h)*sum(h**j*a**(n-j+1) for j in range(n+1))
  lo=math.ceil(line)-1;below=1-above(lo);up=above(math.floor(line));push=pmf(int(line)) if float(line).is_integer() else 0.
  win,loss=(up,below) if side=='over' else (below,up)
 vals=np.maximum(0,[win,push,loss]);return (vals/sum(vals)).tolist()

def masses(candidate,sport,market,side,line=None):
 if market not in ('moneyline','spread','total') or side not in (('over','under') if market=='total' else ('home','away')):raise ValueError('invalid market/side')
 if market=='moneyline':
  if line is not None:raise ValueError('moneyline line')
 elif isinstance(line,bool) or not isinstance(line,(int,float)) or not math.isfinite(line) or abs(line)>500 or line*2!=round(line*2) or (market=='total' and line<.5):raise ValueError('invalid line')
 ss=np.asarray(candidate['scores']);v=ss[:,0]-ss[:,1] if market!='total' else ss.sum(axis=1)
 if side in ('away','under'):v=-v
 v=v+(line or 0) if market=='spread' else v if market=='moneyline' else v-(line if side=='over' else -line)
 raw=np.array([np.mean(v>0),np.mean(v==0),np.mean(v<0)])
 vals=.99*raw+.01*np.asarray(tail(candidate['tail_means'],sport,market,side,line))
 if min(vals)<0 or not math.isclose(sum(vals),1,abs_tol=1e-10):raise ValueError('invalid distribution')
 return (vals/sum(vals)).tolist()

def score(p,y):
 r=proper_scores(p,y);r['infinite']=not math.isfinite(r['threeway_logloss'])
 if r['infinite']:r['threeway_logloss']=None
 if r['conditional_logloss'] is not None and not math.isfinite(r['conditional_logloss']):r['conditional_logloss']=None
 return r

def elo_predictions(rows):
 ratings=defaultdict(lambda:1500.);pending=[];out={}
 for r in rows:
  t=instant(r['kickoff']);due=[v for v in pending if instant(v['result_observed_at'])<t];pending=[v for v in pending if instant(v['result_observed_at'])>=t]
  for v in due:
   h,a=v['home_id'],v['away_id'];delta=20*(v['_y']-v['_p']);ratings[h]+=delta;ratings[a]-=delta
  p=1/(1+10**(-(ratings[r['home_id']]-ratings[r['away_id']]+(0 if r['neutral'] else 55))/400));out[r['event_id']]=p
  pending.append(dict(r,_p=p,_y=1 if r['home_score']>r['away_score'] else .5 if r['home_score']==r['away_score'] else 0))
 return out

def replay(rows,sport):
 origins=sorted({(instant(r['kickoff']).year,(instant(r['kickoff']).month-1)//3) for r in rows})
 oof=[];predictions=[];refusals=[];folds=[];ep=elo_predictions(rows)
 for year,q in origins:
  origin=datetime(year,1+3*q,1,tzinfo=timezone.utc);end=datetime(year+1,1,1,tzinfo=timezone.utc) if q==3 else datetime(year,4+3*q,1,tzinfo=timezone.utc)
  tests=[r for r in rows if origin<=instant(r['kickoff'])<end]
  if sum(instant(r['result_observed_at'])<origin for r in rows)<100:continue
  issue=(origin-timedelta(microseconds=1)).isoformat()
  model,train=build_model(rows,sport,issue,oof);folds.append(dict(origin=origin.isoformat(),issued_at=issue,training=len(train),test=len(tests),status=model['status']))
  for r in tests:
   f=forecast(model,r,issue)
   if f['status']=='REFUSED':refusals.append(dict(event_id=r['event_id'],season=r['season'],reasons=f['reasons']));continue
   errors=(np.asarray([r['home_score'],r['away_score']])-np.asarray(f['point'])).tolist()
   row=dict(event_id=r['event_id'],season=r['season'],kickoff=r['kickoff'],result_observed_at=r['result_observed_at'],features=f['features'],errors=errors,score_base_errors=errors)
   if 'adjusted' in f:row['rest_form_errors']=(np.asarray([r['home_score'],r['away_score']])-np.asarray(f['adjusted'])).tolist()
   oof.append(row)
   if f.get('arms'):
    y=1 if r['home_score']>r['away_score'] else 0 if r['home_score']==r['away_score'] else -1
    grades={}
    for arm,c in f['arms'].items():
     p=masses(c,sport,'moneyline','home');grades[arm]=dict(winner=score(p,y),margin_error=abs(c['point'][0]-c['point'][1]-r['home_score']+r['away_score']),total_error=abs(sum(c['point'])-r['home_score']-r['away_score']))
    predictions.append(dict(event_id=r['event_id'],sport=sport,season=r['season'],kickoff=r['kickoff'],origin=issue,grades=grades,elo_brier=None if y==0 else (ep[r['event_id']]-(y==1))**2,forecast=f))
 return predictions,refusals,folds,oof

def intervals(delta):
 # Paired week-cluster bootstrap; descriptive only, no holdout claim.
 if not delta:return None
 groups=defaultdict(list)
 for t,v in delta:groups[instant(t).strftime('%G-%V')].append(v)
 vals=list(groups.values());rng=np.random.default_rng(POLICY['seed']);boots=[]
 for _ in range(1000):
  z=[v for i in rng.integers(0,len(vals),len(vals)) for v in vals[i]];boots.append(float(np.mean(z)))
 return dict(delta=float(np.mean([v for _,v in delta])),ci95=np.quantile(boots,[.025,.975]).tolist(),week_blocks=len(vals),descriptive=True)

def summarize(pred):
 result={}
 for season in sorted({r['season'] for r in pred}):
  rr=[r for r in pred if r['season']==season];z={}
  for arm in POLICY['arms']:
   a=[r['grades'][arm] for r in rr if arm in r['grades']]
   z[arm]=dict(games=len(a),conditional_winner_brier=float(np.mean([x['winner']['conditional_brier'] for x in a if x['winner']['conditional_brier'] is not None])) if a else None,
    wpl_brier=float(np.mean([x['winner']['threeway_brier'] for x in a])) if a else None,
    infinite=sum(x['winner']['infinite'] for x in a),margin_mae=float(np.mean([x['margin_error'] for x in a])) if a else None,total_mae=float(np.mean([x['total_error'] for x in a])) if a else None)
  paired=[r for r in rr if all(a in r['grades'] for a in POLICY['arms'])]
  z['paired_winner']=intervals([(r['kickoff'],r['grades']['rest_form']['winner']['threeway_brier']-r['grades']['score_base']['winner']['threeway_brier']) for r in paired])
  z['elo_brier']=float(np.mean([r['elo_brier'] for r in paired if r['elo_brier'] is not None])) if paired else None
  result[str(season)]=z
 return result

def market_replay(state):
 """Reconstructed challenger probabilities at existing quotes, never original p."""
 state=Path(state);archive=ROOT/'state/odds-history/ncaaf-20261105-v1/joined-retrospective-quotes.jsonl'
 pred={r['event_id']:r for r in read(state/'NCAAF/predictions.json')}
 history={r['event_id']:r for r in read(state/'NCAAF/history.json')}
 groups=defaultdict(list);reject=Counter();seen=set();cache={}
 for line in archive.open():
  q=json.loads(line)
  if q['selection'] not in ('home','over'):continue
  r=pred.get(str(q['event_id']))
  if r is None:reject['no_challenger_forecast']+=1;continue
  if str(q['event_id']) in QUARANTINES:reject['quarantine']+=1;continue
  # Quote clocks validated against preserved archive; source-time authentication stays false.
  try:original=checked(q)
  except (ValueError,TypeError,KeyError) as e:reject[str(e)]+=1;continue
  if instant(q['start_time_utc'])!=instant(r['kickoff']):reject['kickoff_mismatch']+=1;continue
  actual=history[str(q['event_id'])]
  if [q['home_score'],q['away_score']]!=[actual['home_score'],actual['away_score']]:reject['score_revision']+=1;continue
  key=(q['event_id'],q['book'],q['market'],q['line'],q['quote_time_utc'])
  if key in seen:reject['duplicate_quote']+=1;continue
  seen.add(key)
  for arm,c in r['forecast']['arms'].items():
   mk=(q['event_id'],arm,q['market'],q['line'])
   if mk not in cache:cache[mk]=masses(c,'NCAAF',q['market'],q['selection'],None if q['market']=='moneyline' else q['line'])
   p=cache[mk]
   derived=dict(q,p_win=p[0],p_push=p[1],p_loss=p[2],model_version=VERSION+':'+arm,forecast_time_utc=r['origin'])
   z=checked(derived);z.update(start_time_utc=q['start_time_utc'],kickoff=r['kickoff'],score=score(p,z['outcome']),event_id=q['event_id'],book=q['book'],season=q['season'],market=q['market'])
   groups[(q['season'],q['market'],arm)].append(z)
 results=[]
 for (season,market,arm),rr in groups.items():
  events=defaultdict(list)
  for r in rr:events[r['event_id']].append(r)
  def avg(field):
   vv=[np.mean([field(r) for r in rs if field(r) is not None]) for rs in events.values() if any(field(r) is not None for r in rs)]
   return float(np.mean(vv)) if vv else None
  delta=[];roi_week=defaultdict(lambda:[0.,0]);pnl_by_event=[]
  for eid,rs in events.items():
   non=[r for r in rs if r['outcome']]
   if non:delta.append((rs[0]['kickoff'],float(np.mean([(r['model_conditional_win']-(r['outcome']==1))**2-(r['no_vig_conditional_win']-(r['outcome']==1))**2 for r in non]))))
   sel=[r for r in rs if r['hypothetical_selected']];pnl=sum(r['hypothetical_profit_per_1_risk'] for r in sel)
   pnl_by_event.append((rs[0]['kickoff'],pnl));week=instant(rs[0]['kickoff']).strftime('%G-%V');roi_week[week][0]+=pnl;roi_week[week][1]+=len(sel)
  cum=peak=draw=0.
  for _,pnl in sorted(pnl_by_event):cum+=pnl;peak=max(peak,cum);draw=max(draw,peak-cum)
  vals=list(roi_week.values());rng=np.random.default_rng(POLICY['seed']);boot=[]
  for _ in range(1000):
   ss=np.asarray([vals[i] for i in rng.integers(0,len(vals),len(vals))]).sum(axis=0)
   if ss[1]:boot.append(ss[0]/ss[1])
  results.append(dict(season=season,market=market,arm=arm,events=len(events),quote_metrics=metrics(rr),
   event_weighted_conditional_brier=avg(lambda r:r['score']['conditional_brier']),
   event_weighted_novig_brier=avg(lambda r:(r['no_vig_conditional_win']-(r['outcome']==1))**2 if r['outcome'] else None),
   event_weighted_wpl_brier=avg(lambda r:r['score']['threeway_brier']),
   infinite=sum(r['score']['infinite'] for r in rr),paired_vs_novig=intervals(delta),
   hypothetical_roi_ci95=np.quantile(boot,[.025,.975]).tolist() if boot else None,
   max_drawdown_quote_units=draw,authenticated_clv=None))
 return dict(scope='EXAMINED_DEVELOPMENT_RECONSTRUCTION_NOT_ORIGINAL_FORECASTS',archive_sha256=sha(archive),
  results=results,rejections=dict(reject),NFL='MISSING historical bookmaker-specific paired timestamped quote archive',
  NCAAB='MISSING historical bookmaker-specific paired timestamped quote archive',
  portfolio='one unit per selected book/line quote; correlated quote observations, not an executable portfolio',authenticated=False)

def diagnostic(state,games):
 """Check sign/push/orientation and training feature coverage, without repairing old models."""
 result={}
 for sport,rows in games.items():
  residuals=[]
  for r in read(Path(state)/sport/'predictions.json'):
   for arm,g in r['grades'].items():residuals.append((r['season'],arm,g['margin_error'],g['total_error']))
  result[sport]=dict(games=len(rows),seasons=dict(Counter(r['season'] for r in rows)),
   overtime='NCAAB full-game minutes/possessions available; football game-specific overtime decomposition unavailable',
   live_feature_cutoff=read(Path(state)/sport/'model.json')['cutoff'],
   sign_tests='home spread uses H-A+handicap; away uses A-H+handicap; totals H+A-threshold; complementary W/P/L regression tested',
   full_game_ties=sum(r['home_score']==r['away_score'] for r in rows),
   actual_hist_quote_coverage='NCAAF available under archive assumptions' if sport=='NCAAF' else 'missing',
   numerical_features=POLICY['features'],blocked_features=POLICY['missing_features'],
   ablation='rest_form vs score_base; same eligible games; refusals retained separately',
   original_publication_authenticated=False)
 return result

def build(state,output):
 state=Path(state);output=Path(output);verify(state,False)
 paths=sources();games,excluded=load_games(paths)
 create(state/'sources.json',dict(captured_at=now().isoformat(),files={s:dict(path=str(p),sha256=sha(p)) for s,p in paths.items()},authentication=False))
 create(state/'excluded.json',excluded);report={};artifacts=[]
 for sport,rows in games.items():
  print('REPLAY',sport,len(rows),flush=True)
  pred,ref,folds,oof=replay(rows,sport)
  t=now();origin=datetime(t.year,1+3*((t.month-1)//3),1,tzinfo=timezone.utc)
  final,_=build_model(rows,sport,(origin-timedelta(microseconds=1)).isoformat(),oof)
  for name,data in [('model',final),('history',rows),('predictions',pred),('refusals',ref),('folds',folds)]:
   p=state/sport/(name+'.json');create(p,data);artifacts.append(str(p.relative_to(state)))
  report[sport]=dict(input_games=len(rows),predicted_games=len(pred),refused_games=len(ref),refusal_reasons=dict(Counter(x for r in ref for x in r['reasons'])),seasons=summarize(pred),source_time_authenticated=False,production='NO_GO')
 create(output/'INPUT_AND_SIGN_AUDIT.json',diagnostic(state,games))
 create(output/'MARKET_RESULTS.json',market_replay(state))
 artifacts+=['sources.json','excluded.json','protocol.json','code.json']
 create(state/'artifacts.json',{p:sha(state/p) for p in artifacts});create(output/'DEVELOPMENT_RESULTS.json',report)
 create(output/'SOURCE_MANIFEST.json',read(state/'sources.json'));create(output/'PROTOCOL.json',read(state/'protocol.json'))
 print(json.dumps({s:{k:v for k,v in x.items() if k!='seasons'} for s,x in report.items()},indent=2))
 return report

def append(state,kind,payload):
 state=Path(state);folder=state/kind;folder.mkdir(exist_ok=True)
 journal=state/'journal.jsonl'
 lines=journal.read_text().splitlines() if journal.exists() else [];head='0'*64
 for line in lines:
  e=json.loads(line)
  if e['previous']!=head or sha(state/e['path'])!=e['sha256']:raise ValueError('journal drift')
  head=hashlib.sha256(canonical(e)).hexdigest()
 key=hashlib.sha256(canonical(payload)).hexdigest();p=folder/(key+'.json')
 if p.exists():return False
 create(p,payload);e=dict(previous=head,path=str(p.relative_to(state)),sha256=sha(p))
 with journal.open('a') as f:f.write(canonical(e).decode()+'\n')
 return True

def event_identity(sport,ev):
 c=ev['competitions'][0];sides={x['homeAway']:x for x in c['competitors']}
 def team(side):
  x=sides[side]
  if sport!='NFL':return str(x['id'])
  a=x['team']['abbreviation'];return {'LAR':'LA','WSH':'WAS'}.get(a,a)
 return dict(event_id=str(ev['id']),home_id=team('home'),away_id=team('away'),
  provider_home_id=str(sides['home']['id']),provider_away_id=str(sides['away']['id']),
  kickoff=ev['date'],neutral=c.get('neutralSite',False if sport=='NFL' else None))

def candidate_pairs(data,event):
 result=[]
 for book in data.get('pickcenter',[]):
  h=book.get('homeTeamOdds',{});a=book.get('awayTeamOdds',{})
  if str(h.get('teamId'))!=event['provider_home_id'] or str(a.get('teamId'))!=event['provider_away_id']:continue
  for market,line,left,right in [('moneyline',None,h.get('moneyLine'),a.get('moneyLine')),('spread',book.get('spread'),h.get('spreadOdds'),a.get('spreadOdds')),('total',book.get('overUnder'),book.get('overOdds'),book.get('underOdds'))]:
   if left is None or right is None or (market!='moneyline' and line is None):continue
   pn=implied(left)/(implied(left)+implied(right))
   result.append(dict(market=market,selection='over' if market=='total' else 'home',line=line,
    american_odds=left,opposing_american_odds=right,book=book['provider']['name'],
    book_id=str(book['provider']['id']),no_vig_conditional=pn,quote_publication_at=None,
    scope='full_game_including_overtime_ASSUMPTION',jurisdiction=None,executable=False,authenticated=False))
 return result

def shadow(state,output):
 import requests
 from research.beta_daily import parse_events
 state=Path(state);verify(state);captured=now();pol=read(state/'protocol.json');new=Counter();fail=[]
 with (state/'run.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  # A tiny receipt verifies the existing journal even if no event is eligible.
  append(state,'receipts',dict(at=captured.isoformat(),status='STARTED',approved_risk=0))
  previous=[read(p) for p in (state/'forecasts').glob('*.json')] if (state/'forecasts').exists() else []
  seen={(r['sport'],r['event_id']):r for r in previous}
  oldquotes=[read(p) for p in (state/'quotes').glob('*.json')] if (state/'quotes').exists() else []
  quote_keys={(r['sport'],r['event_id'],r['quote']['book_id'],r['quote']['market'],r['quote']['line']) for r in oldquotes}
  oldgrades=[read(p) for p in (state/'grades').glob('*.json')] if (state/'grades').exists() else []
  grades={(r['sport'],r['event_id']):r for r in oldgrades}
  quarantined={(read(p)['sport'],read(p)['event_id']) for p in (state/'quarantines').glob('*.json')} if (state/'quarantines').exists() else set()
  for sport,route in [('NFL','football/nfl'),('NCAAF','football/college-football'),('NCAAB','basketball/mens-college-basketball')]:
   try:
    events=[];event_sources={}
    dates={(captured+timedelta(days=i)).strftime('%Y%m%d') for i in range(8)}
    dates|={instant(r['identity']['kickoff']).strftime('%Y%m%d') for r in previous if r['sport']==sport}
    for date in sorted(dates):
     url='https://site.api.espn.com/apis/site/v2/sports/'+route+'/scoreboard?limit=1000&dates='+date
     if sport=='NCAAF':url+='&groups=80'
     if sport=='NCAAB':url+='&groups=50'
     r=requests.get(url,timeout=30);r.raise_for_status();body=r.content
     if len(r.json().get('events',[]))>=1000:raise ValueError('calendar possibly truncated')
     source=dict(url=url,observed_at=now().isoformat(),sha256=hashlib.sha256(body).hexdigest(),original_publication_at=None,authenticated=False)
     append(state,'sources',dict(source=source,raw_text=body.decode()))
     for ev in r.json().get('events',[]):events.append(ev);event_sources[str(ev['id'])]=source
    model=read(state/sport/'model.json')
    for ev in events:
     source=event_sources[str(ev['id'])]
     eid=str(ev['id']);c=ev['competitions'][0];event=event_identity(sport,ev);key=(sport,eid)
     if eid in QUARANTINES or key in quarantined:continue
     old=seen.get(key)
     if old and any(old['identity'][k]!=event[k] for k in ('home_id','away_id','kickoff','neutral')):
      append(state,'quarantines',dict(sport=sport,event_id=eid,reason='identity_kickoff_neutral_revision',observed_at=now().isoformat(),original=old['identity'],current=event));quarantined.add(key);new['quarantines']+=1;continue
     if c['status']['type'].get('completed') and old:
      if instant(event['kickoff'])>=now():
       append(state,'quarantines',dict(sport=sport,event_id=eid,reason='provider_final_before_kickoff',observed_at=now().isoformat()));quarantined.add(key);new['quarantines']+=1;continue
      sides={x['homeAway']:x for x in c['competitors']};hs,aws=[int(sides[k]['score']) for k in ('home','away')]
      if key in grades:
       if [hs,aws]!=grades[key]['scores']:append(state,'quarantines',dict(sport=sport,event_id=eid,reason='score_revision',original=grades[key]['scores'],current=[hs,aws],observed_at=now().isoformat()));quarantined.add(key);new['quarantines']+=1
       continue
      if sport!='NFL' and hs==aws:raise ValueError('invalid final tie')
      y=1 if hs>aws else 0 if hs==aws else -1
      gs={arm:score(masses(cf,sport,'moneyline','home'),y) for arm,cf in old['forecast'].get('arms',{}).items()}
      paired=[]
      for q in oldquotes:
       if (q['sport'],q['event_id'])!=key:continue
       qq=q['quote'];result=settlement(dict(home_score=hs,away_score=aws,market=qq['market'],selection=qq['selection'],line=qq['line']))
       paired.append(dict(quote_sha256=hashlib.sha256(canonical(q)).hexdigest(),outcome=result,grades={a:score(p,result) for a,p in q['probabilities'].items()},reference_only=True))
      append(state,'grades',dict(sport=sport,event_id=eid,scores=[hs,aws],winner_grades=gs,quote_grades=paired,observed_at=now().isoformat(),provider_final_authenticated=False));new['grades']+=1;continue
     if instant(event['kickoff'])<=now():continue
     if instant(event['kickoff'])>captured+timedelta(days=7):continue
     if old is None:
      f=forecast(model,event,now().isoformat());old=dict(version=VERSION,sport=sport,event_id=eid,identity=event,issued_at=now().isoformat(),source=source,model_sha256=sha(state/sport/'model.json'),forecast=f,cohort='DESCRIPTIVE_PILOT_EXCLUDED_FROM_CONFIRMATION',approved_risk=0)
      append(state,'forecasts',old);seen[key]=old;new[sport+':'+f['status']]+=1
     # Capture reference pairs only for next48h, every wake until first book/line capture.
     if (instant(event['kickoff'])-now()).total_seconds()>48*3600 or not old['forecast'].get('arms'):continue
     summary_url='https://site.api.espn.com/apis/site/v2/sports/'+route+'/summary?event='+eid
     sr=requests.get(summary_url,timeout=20);sr.raise_for_status();sd=sr.json();sc=sd['header']['competitions'][0]
     if instant(sc['date'])!=instant(event['kickoff']) or instant(event['kickoff'])<=now():raise ValueError('summary kickoff/clock revision')
     ss={x['homeAway']:str(x['team']['id']) for x in sc['competitors']}
     if ss!={'home':event['provider_home_id'],'away':event['provider_away_id']}:raise ValueError('summary participant revision')
     append(state,'sources',dict(source=dict(url=summary_url,observed_at=now().isoformat(),sha256=hashlib.sha256(sr.content).hexdigest(),authenticated=False),raw_text=sr.content.decode()))
     for q in candidate_pairs(sd,event):
      qk=(sport,eid,q['book_id'],q['market'],q['line'])
      if qk in quote_keys:continue
      ps={a:masses(cf,sport,q['market'],q['selection'],q['line']) for a,cf in old['forecast']['arms'].items()}
      append(state,'quotes',dict(sport=sport,event_id=eid,quote=q,probabilities=ps,issued_at=now().isoformat(),forecast_sha256=hashlib.sha256(canonical(old)).hexdigest(),source_sha256=hashlib.sha256(sr.content).hexdigest(),approved_risk=0));quote_keys.add(qk);new[sport+':reference_pairs']+=1
   except Exception as e:fail.append(dict(sport=sport,error=str(e)))
  receipt=dict(at=now().isoformat(),new=dict(new),failures=fail,confirmation_open=False,paid_requests=0,approved_risk=0)
  create(output,receipt);return receipt

def main():
 p=argparse.ArgumentParser();p.add_argument('command',choices=['register','build','shadow']);p.add_argument('--state',required=True,type=Path);p.add_argument('--output',type=Path);a=p.parse_args()
 if a.command=='register':protocol(a.state)
 elif a.command=='build':build(a.state,a.output)
 else:print(json.dumps(shadow(a.state,a.output),indent=2))
if __name__=='__main__':main()
