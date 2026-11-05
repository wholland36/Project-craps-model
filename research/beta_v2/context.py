"""Versioned pregame candidate capture and typed, source-bound research inputs.

Candidate public feeds never become authenticated injury or workload evidence merely
because a request succeeds. Raw bodies remain in the caller's private state folder.
"""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import math
import re
import urllib.request

PATHS={'NFL':'football/nfl','NCAAB':'basketball/mens-college-basketball'}
TTL_SECONDS=900
ROLE_SCALES={'NFL':'NFL_INDEPENDENT_POINTS_PER_FULL_ROLE','NCAAB':'NCAAB_INDEPENDENT_POINTS_PER_FULL_ROLE'}
FEATURE_SCHEMAS={
 'roster':('player_id','team_id','eligible','position'),
 'eligibility':('player_id','team_id','eligible'),
 'coaching':('team_id','head_coach_id','playcaller_id'),
 'weather':('event_id','wind_mph','temperature_f','precipitation_type','roof_status'),
 'three_point':('team_id','attempts','possessions','through_game_id'),
 'foul':('team_id','fouls','possessions','through_game_id'),
 'drive':('team_id','drives','points','non_garbage_drives','through_game_id'),
}

def instant(x):
 d=datetime.fromisoformat(str(x).replace('Z','+00:00'))
 if d.tzinfo is None:raise ValueError('timezone required')
 return d

def finite(x):return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x)
def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def safe(x):
 x=str(x)
 if not re.fullmatch(r'[A-Za-z0-9_.-]+',x) or x in ('.','..'):raise ValueError('unsafe identity/horizon')
 return x

def private_write(path,body):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
 with path.open('xb') as f:f.write(body)
 path.chmod(0o600)

def validate_event(sport,event,asof):
 if sport not in PATHS:raise ValueError('unsupported sport')
 for k in ('event_id','espn_event_id','home_id','away_id','home_espn_id','away_espn_id','kickoff'):
  if event.get(k) is None:raise ValueError('exact canonical and ESPN identities required: '+k)
 if str(event['home_id'])==str(event['away_id']):raise ValueError('same team')
 if not instant(asof)<instant(event['kickoff']):raise ValueError('pregame asof required')
 return True

def capture_candidates(sport,event,asof,state,horizon,fetch=None,now=None):
 """One attempt per immutable 15-minute horizon slot; failures are not retried.

 Capturing with a historical asof is forbidden. Caller may supply a clock/fetch
 only for deterministic tests. All candidate publication clocks stay unknown.
 """
 validate_event(sport,event,asof);safe(horizon);now=now or datetime.now(timezone.utc)
 age=(now-instant(asof)).total_seconds()
 if age<0 or age>TTL_SECONDS:return {'sources':[],'missing':['asof_capture_clock_outside_15min'],'capture_status':'NOT_CAPTURED'}
 root=Path(state)/'context'/sport/safe(event['event_id'])/safe(horizon)
 base='https://site.api.espn.com/apis/site/v2/sports/'+PATHS[sport]
 urls=[base+'/summary?event='+safe(event['espn_event_id']),base+'/injuries']+[base+'/teams/'+safe(event[s+'_espn_id'])+'/roster' for s in ('home','away')]
 slot=int(instant(asof).timestamp())//TTL_SECONDS;sources=[]
 for url in urls:
  token=hashlib.sha256(url.encode()).hexdigest();folder=root/str(slot);receipt=folder/(token+'.receipt.json');body_path=folder/(token+'.body.json')
  if receipt.exists():
   rec=json.loads(receipt.read_text());elapsed=(now-instant(rec['observed_at'])).total_seconds()
   if elapsed<0 or elapsed>TTL_SECONDS:rec=dict(rec,status='EXPIRED_NO_RETRY')
   elif rec['status']=='CAPTURED' and (not body_path.exists() or hashlib.sha256(body_path.read_bytes()).hexdigest()!=rec['sha256']):rec=dict(rec,status='HASH_MISMATCH')
   sources.append(rec);continue
  rec={'url':url,'sport':sport,'event_id':str(event['event_id']),'espn_event_id':str(event['espn_event_id']),'horizon':str(horizon),'asof':str(asof),'observed_at':now.isoformat(),'published_at':None,'authenticated':False,'status':'ERROR_NO_RETRY'}
  try:
   if fetch:body=fetch(url)
   else:
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'ProjectCrapsResearch/2'}),timeout=10) as response:body=response.read()
   json.loads(body);observed=now if fetch else datetime.now(timezone.utc)
   if observed>=instant(event['kickoff']):raise ValueError('capture after kickoff')
   private_write(body_path,body);rec.update(status='CAPTURED',observed_at=observed.isoformat(),sha256=hashlib.sha256(body).hexdigest())
  except Exception as exc:rec['error_type']=type(exc).__name__
  private_write(receipt,(json.dumps(rec,indent=2)+'\n').encode());sources.append(rec)
 return {'sources':sources,'missing':['candidate_sources_are_not_authenticated_reports'],'capture_status':'CAPTURED_CANDIDATES'}

def _source_guard(row,sources,asof):
 flags=[];src=next((s for s in sources if s.get('sha256')==row.get('source_sha256') and s.get('status')=='CAPTURED'),None)
 if src is None:flags.append('source_hash_not_captured');return flags
 if row.get('source_authenticated') is not True:flags.append('source_not_authenticated')
 try:
  if not instant(row['published_at'])<=instant(src['observed_at'])<=instant(asof):flags.append('source_after_asof_or_publication_inconsistent')
  if (instant(asof)-instant(row['published_at'])).total_seconds()>float(row.get('max_age_seconds',86400)):flags.append('source_stale')
 except (KeyError,ValueError,TypeError):flags.append('publication_clock_unverified')
 return flags

def validate_roles(sport,event,asof,rows,sources):
 known=[];unknown=[];keys=[(r.get('team_id'),r.get('player_id')) for r in rows]
 for row in rows:
  flags=_source_guard(row,sources,asof)
  if keys.count((row.get('team_id'),row.get('player_id')))>1:flags.append('duplicate_player')
  if row.get('sport')!=sport or str(row.get('event_id'))!=str(event['event_id']) or str(row.get('team_id')) not in (str(event['home_id']),str(event['away_id'])) or not row.get('player_id'):flags.append('exact_identity_missing')
  for k in ('identity_verified','role_verified','workload_verified','replacement_verified'):
   if row.get(k) is not True:flags.append(k+'_missing')
  if row.get('status') not in ('Out','Available','Limited','Questionable'):flags.append('status_unknown')
  if row.get('value_scale')!=ROLE_SCALES[sport]:flags.append('independent_sport_scale_missing')
  if not finite(row.get('workload')) or not 0<=row['workload']<=1:flags.append('workload_missing')
  if sport=='NFL' and row.get('position')=='QB' and (not row.get('qb_role_verified') or not row.get('replacement_player_ids')):flags.append('verified_qb_backup_missing')
  if sport=='NCAAB' and row.get('workload_type') not in ('minutes_share','usage_share'):flags.append('basketball_workload_type_missing')
  if row.get('status') in ('Limited','Questionable'):
   scenarios=row.get('scenarios')
   if not isinstance(scenarios,list) or not scenarios or any(not finite(s.get('restoration_fraction')) or not 0<=s['restoration_fraction']<=1 for s in scenarios):flags.append('return_scenarios_missing')
   if any('probability' in s for s in (scenarios or [])):flags.append('unfitted_scenario_probability_forbidden')
  (unknown if flags else known).append(dict(row,missing_flags=sorted(set(flags))))
 return known,unknown

def validate_features(rows,sources,asof):
 known=[];unknown=[]
 for row in rows:
  flags=_source_guard(row,sources,asof);kind=row.get('kind');required=FEATURE_SCHEMAS.get(kind)
  if required is None:flags.append('unknown_feature_schema')
  else:
   flags.extend('missing_'+k for k in required if k not in row or row[k] is None)
  try:
   if instant(row['effective_from'])>instant(asof):flags.append('not_effective_yet')
   if row.get('effective_to') and instant(row['effective_to'])<=instant(asof):flags.append('no_longer_effective')
   if kind in ('three_point','foul','drive') and instant(row['statistics_through'])>=instant(asof):flags.append('statistics_not_prior')
  except (KeyError,ValueError):flags.append('effective_clock_missing')
  (unknown if flags else known).append(dict(row,missing_flags=sorted(set(flags))))
 return known,unknown

def collect_context(sport,event,asof,state,horizon):
 capture=capture_candidates(sport,event,asof,state,horizon)
 inbox=Path(state)/'context'/'inbox'/sport/(safe(event['event_id'])+'_'+safe(horizon)+'.json')
 data=json.loads(inbox.read_text()) if inbox.exists() else {}
 # Typed local receipts must bind private bytes, never trust a supplied digest alone.
 sources=list(capture['sources'])
 for supplied in data.get('sources',[]):
  s=dict(supplied)
  try:
   p=Path(s['body_path']).resolve();root=Path(state).resolve()
   if root not in p.parents:raise ValueError('source outside private state')
   if hashlib.sha256(p.read_bytes()).hexdigest()!=s['sha256']:raise ValueError('source hash mismatch')
   if instant(s['observed_at'])>instant(asof):raise ValueError('source after asof')
   s['status']='CAPTURED'
  except (KeyError,ValueError,OSError):s['status']='SOURCE_INVALID'
  sources.append(s)
 known,unknown=validate_roles(sport,event,asof,data.get('players',[]),sources)
 fk,fu=validate_features(data.get('features',[]),sources,asof)
 return {'sport':sport,'event_id':str(event['event_id']),'horizon':horizon,'asof':asof,'sources':sources,'known':known,'unknown':unknown,'known_features':fk,'unknown_features':fu,'missing':capture['missing']+([] if inbox.exists() else ['verified_role_inbox_missing']),'rotation_by_team':data.get('rotation_by_team',{}),'complete_coverage':False,'research_only':True}

def validate_value_model(model,sport,asof):
 """Validate an externally fitted model; this interface never invents coefficients."""
 flags=[];binding={k:v for k,v in model.items() if k!='sha256'}
 if model.get('sha256')!=digest(binding):flags.append('model_hash_invalid')
 if model.get('sport')!=sport or model.get('value_scale')!=ROLE_SCALES[sport]:flags.append('sport_scale_mismatch')
 if model.get('independently_trained') is not True:flags.append('independent_training_missing')
 try:
  if instant(model['trained_through'])>=instant(asof):flags.append('training_not_prior')
 except (KeyError,ValueError):flags.append('training_clock_missing')
 if not model.get('training_source_sha256'):flags.append('training_source_hash_missing')
 for group,coef in model.get('coefficients',{}).items():
  support=model.get('support',{}).get(group,{})
  if not finite(coef) or support.get('exposures',0)<max(30,model.get('minimum_exposures',30)) or support.get('design_rank',0)<max(1,support.get('required_rank',1)):flags.append('unidentified_'+group)
 if not model.get('coefficients'):flags.append('coefficients_missing')
 return {'valid':not flags,'missing':flags,'status':'VALIDATED_FITTED_INTERFACE' if not flags else 'UNFITTED_OR_UNIDENTIFIED'}

def allocate_non_qb(losses,roster):
 """User's independent next-three prior; capacity depletion is separate scenario."""
 out=[];used=set();lost={x['player_id'] for x in losses}
 for loss in sorted(losses,key=lambda x:(-x['rating'],x['player_id'])):
  if loss.get('position')=='QB':out.append({'player_id':loss['player_id'],'missing':['verified_qb_required']});continue
  pool=sorted((r for r in roster if r['team_id']==loss['team_id'] and r['position']==loss['position'] and r['player_id'] not in lost and r.get('status')=='Available' and r['rating']<loss['rating']),key=lambda r:(-r['rating'],r['player_id']))
  actual=loss.get('actual_replacement_id') if loss.get('actual_replacement_verified') else None
  if actual:
   primary=[r for r in roster if r['player_id']==actual and r['team_id']==loss['team_id'] and r['position']==loss['position'] and r.get('status')=='Available' and r['player_id'] not in lost]
  else:primary=pool[:3]
  capacity=[r for r in primary if r['player_id'] not in used] if actual else [r for r in pool if r['player_id'] not in used][:3]
  used.update(r['player_id'] for r in capacity)
  out.append({'player_id':loss['player_id'],'primary_ids':[r['player_id'] for r in primary],'primary_rating':sum(r['rating'] for r in primary)/len(primary) if primary else None,'capacity_scenario_ids':[r['player_id'] for r in capacity],'capacity_scenario_rating':sum(r['rating'] for r in capacity)/len(capacity) if capacity else None,'capacity_assumption':'exclusive proxy-pool sensitivity, not actual workload','missing':[] if primary else ['replacement_unresolved']})
 return out

def validate_rotation(rows,sport):
 flags=[];seen=set();total=0.;roles={}
 for r in rows:
  pid=r.get('player_id')
  if not pid or pid in seen:flags.append('duplicate_or_missing_player')
  seen.add(pid)
  if sport=='NCAAB':
   minutes=r.get('regulation_minutes')
   if not finite(minutes) or not 0<=minutes<=40:flags.append('invalid_player_minutes')
   else:total+=minutes
  elif sport=='NFL':
   role=r.get('role');share=r.get('role_share');cap=r.get('role_capacity')
   if not role or not finite(share) or share<0 or not finite(cap) or cap<=0:flags.append('role_capacity_missing')
   else:
    prior=roles.setdefault(role,{'share':0.,'capacity':cap})
    if prior['capacity']!=cap:flags.append('inconsistent_role_capacity')
    prior['share']+=share
  else:flags.append('unsupported_sport')
 if sport=='NCAAB' and abs(total-200)>1e-6:flags.append('rotation_not_200_regulation_minutes')
 if sport=='NFL' and any(x['share']>x['capacity']+1e-9 for x in roles.values()):flags.append('role_capacity_exceeded')
 return {'valid':not flags,'missing':sorted(set(flags)),'regulation_minutes':total if sport=='NCAAB' else None}

def fit_value_model(rows,sport,trained_through,groups,minimum_exposures=30):
 """Constrained fit interface for independently source-verified historical residuals.

 Each row requires a pregame source-bound `features` mapping (signed, centered
 burden innovation), `residual_margin`, `features_observed_at`, `outcome_at`, and
 source hashes for verified features and outcomes. Callers must compute residuals
 out of sample against a frozen comparator; an intercept is deliberately omitted
 so this arm cannot masquerade as a generic bias correction. No live fit is run by
 collect_context. Sparse/unidentified groups prevent fitting rather than receive
 a made-up zero coefficient.
 """
 import numpy as np
 from scipy.optimize import nnls
 if sport not in ROLE_SCALES or not groups or len(set(groups))!=len(groups):raise ValueError('explicit supported groups required')
 minimum_exposures=max(30,int(minimum_exposures));accepted=[];excluded=[]
 event_ids=[str(r.get('event_id')) for r in rows]
 for i,row in enumerate(rows):
  flags=[]
  if not row.get('event_id') or event_ids.count(str(row.get('event_id')))>1:flags.append('unique_event_required')
  if row.get('sport')!=sport or row.get('independent_oos_residual') is not True or row.get('features_authenticated') is not True or row.get('outcome_verified') is not True:flags.append('independent_verified_training_row_required')
  if not row.get('feature_source_sha256') or not row.get('outcome_source_sha256'):flags.append('source_hash_missing')
  try:
   if not instant(row['features_observed_at'])<instant(row['kickoff'])<=instant(row['outcome_at'])<=instant(trained_through):flags.append('training_time_violation')
  except (KeyError,ValueError):flags.append('training_clock_missing')
  f=row.get('features',{})
  if any(not finite(f.get(g)) for g in groups) or not finite(row.get('residual_margin')):flags.append('finite_features_target_required')
  if flags:excluded.append({'row':i,'missing':flags})
  else:accepted.append(row)
 if not accepted:return {'status':'UNFITTED','missing':['verified_training_rows_missing'],'excluded':excluded}
 x=np.array([[r['features'][g] for g in groups] for r in accepted]);y=np.array([r['residual_margin'] for r in accepted]);rank=int(np.linalg.matrix_rank(x));support={g:{'exposures':int(np.count_nonzero(x[:,i])),'design_rank':rank,'required_rank':len(groups)} for i,g in enumerate(groups)}
 if rank<len(groups) or any(v['exposures']<minimum_exposures for v in support.values()):return {'status':'UNFITTED','missing':['exposure_or_design_rank_insufficient'],'support':support,'accepted_rows':len(accepted),'excluded':excluded}
 coeff,resnorm=nnls(x,y)
 m={'sport':sport,'value_scale':ROLE_SCALES[sport],'independently_trained':True,'trained_through':trained_through,'training_source_sha256':sorted({r[k] for r in accepted for k in ('feature_source_sha256','outcome_source_sha256')}),'training_rows_sha256':digest(accepted),'coefficients':dict(zip(groups,map(float,coeff))),'support':support,'minimum_exposures':minimum_exposures,'feature_convention':'home_margin_signed_burden_innovation','method':'nonnegative-no-intercept-oos-residual-v1','train_n':len(accepted),'training_residual_norm':float(resnorm),'research_only':True,'production_approved':False}
 m['sha256']=digest(m)
 return {'status':'FITTED_RESEARCH_ONLY','model':m,'excluded':excluded}


def apply_value_model(context,event,model,asof):
 """Mean-only injury innovation; no probability distribution or betting claim.

 Values must already use independent sport-specific role units. Workloads and
 baseline absorption are never inferred here and no OVR-to-point conversion is
 performed. Uncertain returns remain explicit unweighted scenarios.
 """
 sport=context.get('sport');result={'status':'NOT_COMPUTED','delta_mean_margin':None,'missing':[],'research_only':True,'probability_adjustment':None}
 if sport not in ROLE_SCALES:result['missing']=['unsupported_sport'];return result
 try:
  validate_event(sport,event,asof)
 except ValueError as exc:result['missing']=[str(exc)];return result
 if str(context.get('event_id'))!=str(event['event_id']) or context.get('asof')!=asof:result['missing']=['context_identity_or_asof_mismatch'];return result
 check=validate_value_model(model or {},sport,asof)
 if not check['valid']:result['missing']=check['missing'];return result
 if model.get('feature_convention')!='home_margin_signed_burden_innovation':result['missing']=['model_feature_convention_missing'];return result
 rows=context.get('known',[])
 if not rows:result['missing']=['verified_known_roles_missing'];return result
 # Revalidate the claimed known rows; never trust classification supplied by caller.
 known,unknown=validate_roles(sport,event,asof,rows,context.get('sources',[]))
 if unknown:result['missing']=['known_role_revalidation_failed'];return result
 if any(r['status'] not in ('Out','Available') for r in known):
  result['missing']=['uncertain_returns_require_unweighted_scenarios'];result['scenarios']=[{'player_id':r['player_id'],'scenarios':r.get('scenarios',[])} for r in known if r['status'] not in ('Out','Available')];return result
 groups=model.get('coefficients',{});delta=0.
 for team in {str(r['team_id']) for r in known}:
  losses=[r for r in known if str(r['team_id'])==team and r['status']=='Out']
  if len(losses)>1:
   evidence=context.get('rotation_by_team',{}).get(team,{})
   if evidence.get('complete_rotation_verified') is not True or set(evidence.get('covered_loss_ids',[]))!={r['player_id'] for r in losses} or evidence.get('source_authenticated') is not True or not evidence.get('source_sha256') or _source_guard(evidence,context.get('sources',[]),asof):result['missing']=['verified_multiple_loss_rotation_missing'];return result
   rotation=validate_rotation(evidence.get('rows',[]),sport)
   if not rotation['valid']:result['missing']=['multiple_loss_rotation_infeasible']+rotation['missing'];return result
 for r in known:
  group=r.get('group');burden=r.get('burden_innovation')
  if group not in groups or not finite(burden):result['missing']=['identified_group_and_explicit_burden_innovation_required'];return result
  # Burden units already contain verified workload and embedded-state subtraction.
  delta+=(-1 if str(r['team_id'])==str(event['home_id']) else 1)*groups[group]*burden
 result.update(status='COMPUTED_MEAN_ONLY_KNOWN_INPUTS',delta_mean_margin=delta,known_inputs=len(known),coverage='known_inputs_only_not_complete_report')
 return result
