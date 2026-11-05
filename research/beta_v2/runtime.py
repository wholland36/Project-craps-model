"""Independent immutable multi-horizon beta experiments; no official writes."""
import argparse,fcntl,hashlib,json,math,shutil
from collections import Counter,defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import requests
from research.validation_v2 import canonical,sha,instant
from research.beta_daily import official_check,parse_events,journaled_save,verify_journal,integrity
from research.probability_v2 import weighted_outcome_masses,week_block_ci
from .protocol import VERSION,PROTOCOL,horizon,readiness
from . import benchmarks
from .strength import predict
from .calibration import apply,proper_scores
from .context import collect_context,validate_value_model,validate_roles,validate_features,apply_value_model
from .markets import match_quotes,choose_ticket,settle as settle_ticket,summarize_returns

STATE=Path('/Users/wadeholland/Documents/Codex/Project-Craps/state/research-extensions/beta-v2-20261105')
SPORTS={'NFL':'football/nfl','NCAAB':'basketball/mens-college-basketball'}

def clock():return datetime.now(timezone.utc)
def dump(path,value):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 with path.open('xb') as f:f.write(canonical(value))
 path.chmod(0o600)

def algorithm_check(state):
 official_check();p=state/'algorithm.json'
 if not p.exists():raise ValueError('frozen algorithm missing')
 a=json.loads(p.read_text())
 for f,h in a['files'].items():
  if sha(Path(f).read_bytes())!=h:raise ValueError('beta algorithm drift: '+f)
 return a

def freeze_bundle(state,source):
 state=Path(state);source=Path(source);files={}
 for k in ['strength','calibration']:
  for s in SPORTS:
   p=source/k/(s+'.json');files[k+'/'+s+'.json']=sha(p.read_bytes())
 for name in ['NFL-normalized.json','NCAAB-normalized.json','source-manifest.json','excluded-retained.json','current-ncaab/schedule-2027.parquet','current-ncaab/box-2027.parquet','current-ncaab/receipts.json']:
  p=source/'data'/name;files['data/'+name]=sha(p.read_bytes())
 key=sha(canonical(files));folder=state/'bundles'/key
 if not folder.exists():
  for name in files:
   dest=folder/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source/name,dest)
  dump(folder/'manifest.json',dict(files=files,created_at=clock().isoformat(),version=VERSION))
 # CURRENT is a research pointer. Previous bundles and their records are immutable.
 current=dict(bundle=str(folder),manifest_sha256=sha((folder/'manifest.json').read_bytes()),created_at=clock().isoformat())
 tmp=state/'CURRENT.tmp';tmp.write_bytes(canonical(current));tmp.replace(state/'CURRENT.json')
 return current

def load_bundle(state):
 p=json.loads((state/'CURRENT.json').read_text());folder=Path(p['bundle'])
 if sha((folder/'manifest.json').read_bytes())!=p['manifest_sha256']:raise ValueError('bundle manifest changed')
 m=json.loads((folder/'manifest.json').read_text())
 for f,h in m['files'].items():
  if sha((folder/f).read_bytes())!=h:raise ValueError('bundle input/model changed')
 models={}
 for s in SPORTS:
  strength=json.loads((folder/'strength'/(s+'.json')).read_text());cal=json.loads((folder/'calibration'/(s+'.json')).read_text())
  if sha((folder/'strength'/(s+'.json')).read_bytes())!=cal['parent']['model_sha256']:raise ValueError('wrong calibration parent')
  models[s]=(strength,cal)
 return folder,p,models

def prepare(state,output):
 algorithm_check(state);date=clock().astimezone(ZoneInfo('America/New_York')).date().isoformat();receipt=state/'preparations'/(date+'.json')
 if receipt.exists():return json.loads(receipt.read_text())
 from .training import run as train
 from .calibration import build as calibrate
 stage=state/'builds'/date
 if stage.exists():raise ValueError('incomplete daily preparation requires explicit audit, not overwrite')
 train(stage,output/'training'/date);calibrate(stage,output/'calibration'/date);result=freeze_bundle(state,stage);dump(receipt,result);return result

def calendar(state):
 now=clock();dates={(now+timedelta(days=d)).strftime('%Y%m%d') for d in [-2,-1,0,1,2]}
 for f in (state/'forecasts').glob('*.json'):
  if not (state/'settlements'/f.name).exists():dates.add(instant(integrity(f)['identity']['kickoff']).strftime('%Y%m%d'))
 slot=int(now.timestamp())//900;events={s:{} for s in SPORTS};sources=[];errors=[]
 def get(args):
  s,date=args;root=state/'calendar'/str(slot)/s;receipt=root/(date+'.receipt.json');body=root/(date+'.body.json')
  try:
   if receipt.exists():
    rec=json.loads(receipt.read_text());raw=body.read_bytes()
    if sha(raw)!=rec['sha256']:raise ValueError('calendar hash changed')
   else:
    params=dict(dates=date,limit=1000)
    if s=='NCAAB':params['groups']=50
    r=requests.get('https://site.api.espn.com/apis/site/v2/sports/'+SPORTS[s]+'/scoreboard',params=params,timeout=25);r.raise_for_status();raw=r.content;rec=dict(url=r.url,observed_at=clock().isoformat(),sha256=sha(raw),original_publication_at=None)
    root.mkdir(parents=True,exist_ok=True)
    with body.open('xb') as f:f.write(raw)
    body.chmod(0o600);dump(receipt,rec)
   data=json.loads(raw)
   if len(data.get('events',[]))>=1000:raise ValueError('possible truncated calendar')
   es=parse_events(data,s,rec['observed_at'])
   for e in es:
    e['event_id']=e['espn_event_id'];e['source_sha256']=rec['sha256'];e['market_scope']='including_overtime'
    if s=='NFL':e['home_id']=benchmarks.nfl_alias(e['home_id']);e['away_id']=benchmarks.nfl_alias(e['away_id'])
   return s,es,rec,None
  except Exception as e:return s,[],None,dict(sport=s,date=date,error=str(e))
 with ThreadPoolExecutor(max_workers=6) as ex:results=list(ex.map(get,[(s,d) for s in SPORTS for d in sorted(dates)]))
 for s,es,rec,error in results:
  if error:errors.append(error);continue
  sources.append(rec)
  for e in es:
   old=events[s].get(e['event_id'])
   if old and (old['home_id'],old['away_id'],instant(old['kickoff']))!=(e['home_id'],e['away_id'],instant(e['kickoff'])):raise ValueError('calendar cross-capture identity revision')
   if old is None or instant(e['observed_at'])>instant(old['observed_at']):events[s][e['event_id']]=e
 return events,sources,errors

def candidate(scores,sport):
 if isinstance(scores,dict):c=scores
 else:c=dict(scores=scores,weights=[1/len(scores)]*len(scores))
 if sport=='NCAAB' and any(h==a for h,a in c['scores']):raise ValueError('NCAAB final support tied')
 return c

def make_arm(c,sport):
 pm=sum((h-a)*w for (h,a),w in zip(c['scores'],c['weights']));pt=sum((h+a)*w for (h,a),w in zip(c['scores'],c['weights']));lines=[('moneyline','home',None),('spread','home',-round(pm*2)/2),('total','over',max(.5,round(pt*2)/2))]
 return dict(status='REGISTERED',point_margin=pm,point_total=pt,masses={f'{m}:{s}:{line}':weighted_outcome_masses(c,m,s,line) for m,s,line in lines}),lines

def score_at(c,lines):return {f'{m}:{s}:{line}':weighted_outcome_masses(c,m,s,line) for m,s,line in lines}

def outcome(key,event):
 market,side,line=key.split(':');margin=event['home_score']-event['away_score'];total=event['home_score']+event['away_score']
 value=margin*(1 if side=='home' else -1) if market=='moneyline' else margin*(1 if side=='home' else -1)+float(line) if market=='spread' else (total-float(line))*(1 if side=='over' else -1)
 return 0 if value>0 else 1 if value==0 else 2

def grade(record,event):
 if event['status']!='FINAL':return None
 if instant(record['issued_at'])>=instant(event['kickoff']) or instant(event['observed_at'])<=instant(event['kickoff']):raise ValueError('invalid forecast/result clocks')
 if any(record['identity'][k]!=event[k] for k in ['home_id','away_id']) or instant(record['identity']['kickoff'])!=instant(event['kickoff']):raise ValueError('result identity revision')
 margin=event['home_score']-event['away_score'];total=event['home_score']+event['away_score'];grades={}
 for name,a in record['arms'].items():
  if a.get('status')=='MEAN_ONLY':
   grades[name]=dict(mean_only=True,margin_mae=abs(a['point_margin']-margin));continue
  if a.get('status')!='REGISTERED':continue
  grades[name]=dict(markets={key:proper_scores(p,outcome(key,event)) for key,p in a['masses'].items()},actual_lines={key:proper_scores(p,outcome(key,event)) for key,p in a.get('actual_masses',{}).items()},margin_mae=abs(a['point_margin']-margin),total_mae=abs(a['point_total']-total))
 winner=int(margin>0);bench={}
 if margin:
  for name,p in record['winner_benchmarks'].items():
   if p is not None:bench[name]=dict(conditional_brier=(p-winner)**2,logloss=-math.log(p if winner else 1-p) if 0<p<1 else None,logloss_infinite=not 0<p<1)
 market_benchmarks=[]
 for q in record.get('quote_data',[]):
  oi=outcome(q['key'],event)
  market_benchmarks.append(dict(q,outcome=oi,conditional_brier=(q['conditional_no_vig']-int(oi==0))**2 if oi!=1 else None))
 ticket=record.get('hypothetical_ticket');ret=None
 if ticket:
  key=f"{ticket['market']}:{ticket['side']}:{ticket.get('line')}";res=['win','push','loss'][outcome(key,event)];ticket=dict(ticket,week=f"{event['season']}-{instant(event['kickoff']).isocalendar()[1]}");ret=settle_ticket(ticket,res)
 return dict(sport=record['sport'],event_id=record['event_id'],horizon=record['horizon'],identity=record['identity'],issued_at=record['issued_at'],grades=grades,winner_benchmarks=bench,hypothetical_return=ret,market_benchmarks=market_benchmarks,home_score=event['home_score'],away_score=event['away_score'],observed_at=event['observed_at'],week=instant(event['kickoff']).isocalendar()[1],season=event['season'],official_pnl=0,primary_supported=record['primary_supported'])

def run(state,output,capture_context=True):
 algorithm=algorithm_check(state);verify_journal(state);bundle,binding,models=load_bundle(state);events,sources,errors=calendar(state);now=clock();new=Counter();quarantine=[]
 due={s:[e for e in events[s].values() if e['status'] not in ['FINAL','INVALID_FINAL_TIE'] and horizon(e['kickoff'],now.isoformat())] for s in SPORTS}
 refs={}
 try:refs['NFL']=benchmarks.nfl(due['NFL'],json.loads((bundle/'data/NFL-normalized.json').read_text()),clock().isoformat())
 except Exception as e:refs['NFL']={};errors.append(dict(sport='NFL',stage='official_reference',error=str(e)))
 try:refs['NCAAB']=benchmarks.ncaab(due['NCAAB'],clock().isoformat(),bundle/'data/current-ncaab')
 except Exception as e:refs['NCAAB']={};errors.append(dict(sport='NCAAB',stage='official_reference',error=str(e)))
 existing=[integrity(p) for p in (state/'forecasts').glob('*.json')];selected=[r['event_id'] for r in existing if r.get('hypothetical_ticket')]
 today=clock().astimezone(ZoneInfo('America/New_York')).date();risk=sum(r['hypothetical_ticket']['stake'] for r in existing if r.get('hypothetical_ticket') and instant(r['issued_at']).astimezone(ZoneInfo('America/New_York')).date()==today)
 for sport in SPORTS:
  model,cal=models[sport]
  for event in due[sport]:
   asof=clock().isoformat();label=horizon(event['kickoff'],asof)
   if label is None:continue
   key=f"{sport}-{event['event_id']}-{label}-{VERSION}";path=state/'forecasts'/(key+'.json')
   # Distinct horizon keys allow final capture after a first/day-ahead forecast.
   if path.exists():continue
   ref=refs[sport].get(event['event_id'],dict(status='OFFICIAL_COMPARATOR_UNAVAILABLE'));arms={};candidates={};lines=[]
   if ref.get('scores'):
    candidates['official_score_reference']=candidate(ref['scores'],sport);arms['official_score_reference'],lines=make_arm(candidates['official_score_reference'],sport)
   p=predict(model,event)
   if p.get('paired_score_samples'):
    scores=p['paired_score_samples'];candidates['rolling_strength']=candidate(scores,sport)
    parents=cal['parent'];actual=sha((bundle/'strength'/(sport+'.json')).read_bytes())
    if parents['model_sha256']!=actual:raise ValueError('parent model hash mismatch')
    ps=p['point_scores'];candidates['rolling_calibrated']=apply(scores,cal,dict(predicted_margin=ps[0]-ps[1],predicted_total=sum(ps),parent=parents))
    if not lines:_,lines=make_arm(candidates['rolling_strength'],sport)
   for name,c in candidates.items():
    a,_=make_arm(c,sport);a['masses']=score_at(c,lines);arms[name]=a
   context=collect_context(sport,event,asof,state,label) if capture_context else dict(missing=['context_capture_skipped_explicitly'],known=[],unknown=[])
   issued=clock().isoformat()
   if context.get('sources'):
    context['known'],context['unknown']=validate_roles(sport,event,issued,context.get('known',[])+context.get('unknown',[]),context['sources'])
    context['known_features'],context['unknown_features']=validate_features(context.get('known_features',[])+context.get('unknown_features',[]),context['sources'],issued)
    context['asof']=issued
   if horizon(event['kickoff'],issued)!=label:quarantine.append(dict(sport=sport,event_id=event['event_id'],reason='horizon_changed_during_capture'));continue
   quotes=match_quotes(sport,event,issued,state,label);quote_forecasts={};paired_data=[]
   for pair in quotes['pairedrows']:
    for q in pair['rows']:
     m=q['market'];side=q['side'];line=q.get('line') if m!='moneyline' else None;k=f'{m}:{side}:{line}'
     for name,c in candidates.items():
      masses=weighted_outcome_masses(c,m,side,line);arms[name].setdefault('actual_masses',{})[k]=masses
      if name=='rolling_calibrated':quote_forecasts[q['quote_id']]=dict(zip(['win','push','loss'],masses))
     paired_data.append(dict(quote_id=q['quote_id'],key=k,conditional_no_vig=q['no_vig_probability'],book=q['book']))
   ticket=None
   if risk<5:
    choice=choose_ticket(event['event_id'],[x for x in quotes['pairedrows'] if x['book']=='Hard Rock Florida'],quote_forecasts,already_selected=selected)
    ticket=choice['ticket']
    if ticket and risk+ticket['stake']<=5:risk+=ticket['stake'];selected.append(event['event_id'])
    else:ticket=None
   winner=ref.get('official_winner_probability');mass=arms.get('official_score_reference',{}).get('masses',{}).get('moneyline:home:None')
   if sport=='NFL' and mass and mass[0]+mass[2]>0:winner=mass[0]/(mass[0]+mass[2])
   arms['injury']=dict(status='NOT_COMPUTED',reason='independently_identified_values_and_verified_roles_required',known_roles=len(context.get('known',[])),unknown_roles=len(context.get('unknown',[])))
   injury_path=state/'injury-models'/(sport+'.json')
   if injury_path.exists():
    im=json.loads(injury_path.read_text())
    if im.get('reference_model_sha256')==cal['parent']['model_sha256'] and im.get('reference_scope')=='rolling_strength_point_mean':
     adj=apply_value_model(context,event,im,issued)
     if adj.get('delta_mean_margin') is not None and p.get('point_scores'):
      arms['injury']=dict(status='MEAN_ONLY',point_margin=p['point_scores'][0]-p['point_scores'][1]+adj['delta_mean_margin'],diagnostic=adj,value_model_sha256=sha(injury_path.read_bytes()),reason='No injury-adjusted probability distribution inferred')
     else:arms['injury']['diagnostic']=adj
    else:arms['injury']['reason']='injury_value_comparator_binding_missing_or_changed'
   primary=all(n in candidates for n in ['official_score_reference','rolling_strength','rolling_calibrated']) and winner is not None
   record=dict(version=VERSION,sport=sport,event_id=event['event_id'],horizon=label,issued_at=issued,identity={k:event[k] for k in ['home_id','away_id','home','away','kickoff','espn_event_id']},bundle=binding,protocol_sha256=sha(canonical(PROTOCOL)),arms=arms,winner_benchmarks=dict(official_winner=winner,independent_elo=ref.get('independent_elo')),official_reference_metadata={k:v for k,v in ref.items() if k not in ['scores','official_winner_probability','independent_elo']},context=context,quote_data=paired_data,quote_rows=[q for pair in quotes['pairedrows'] for q in pair['rows']],quote_missing=quotes['missing'],hypothetical_ticket=ticket,primary_supported=primary,source_authentication_verified=False,approved_risk=0,note='New beta inference at recorded time; original forecasts unchanged')
   journaled_save(state,path,record);new[sport+':'+label]+=1
 for path in (state/'forecasts').glob('*.json'):
  r=integrity(path);event=events[r['sport']].get(r['event_id'])
  if not event or event['status']!='FINAL':continue
  try:g=grade(r,event)
  except ValueError as e:quarantine.append(dict(sport=r['sport'],event_id=r['event_id'],reason=str(e)));continue
  target=state/'settlements'/path.name
  if target.exists():
   old=integrity(target)
   if (old['home_score'],old['away_score'])!=(g['home_score'],g['away_score']):quarantine.append(dict(event_id=r['event_id'],reason='result_revision_preserved'))
   continue
  journaled_save(state,target,g)
 status=report(state,output);status.update(run_at=clock().isoformat(),new_forecasts=dict(new),source_errors=errors,quarantines=quarantine,paid_calls=0,official_mutations=0,journal_anchor=verify_journal(state))
 (output/'latest-v2-status.json').write_text(json.dumps(status,indent=2));dump(state/'runs'/(clock().strftime('%Y%m%dT%H%M%S%fZ')+'.json'),status);return status

def report(state,output):
 output=Path(output);output.mkdir(parents=True,exist_ok=True);rs=[integrity(f) for f in (state/'forecasts').glob('*.json')];gs=[integrity(f) for f in (state/'settlements').glob('*.json')];summary={}
 for sport in SPORTS:
  summary[sport]={}
  for label in ['DAY_AHEAD','EARLY','FINAL']:
   r=[r for r in rs if r['sport']==sport and r['horizon']==label];g=[g for g in gs if g['sport']==sport and g['horizon']==label and g['primary_supported']];metrics={}
   for name in ['official_score_reference','rolling_strength','rolling_calibrated']:
    rr=[x for x in g if name in x['grades']];markets={}
    for market in ['moneyline','spread','total']:
     vals=[v for x in rr for k,v in x['grades'][name]['markets'].items() if k.startswith(market+':')];finite=[v['threeway_logloss'] for v in vals if not v['logloss_is_infinite']]
     actual=[]
     for x in rr:
      hits=[]
      for q in x.get('market_benchmarks',[]):
       k=q['key'];v=x['grades'][name]['actual_lines'].get(k)
       if k.startswith(market+':') and v and v['conditional_brier'] is not None and q['conditional_brier'] is not None:hits.append((v['conditional_brier'],q['conditional_brier']))
      if hits:actual.append((sum(a for a,b in hits)/len(hits),sum(b for a,b in hits)/len(hits)))
     markets[market]=dict(actual_quote_games=len(actual),actual_conditional_brier=sum(a for a,b in actual)/len(actual) if actual else None,same_book_no_vig_brier=sum(b for a,b in actual)/len(actual) if actual else None,games=len(vals),wpl_brier=sum(v['threeway_brier'] for v in vals)/len(vals) if vals else None,logloss=None if any(v['logloss_is_infinite'] for v in vals) else sum(finite)/len(finite) if finite else None,logloss_is_infinite=any(v['logloss_is_infinite'] for v in vals),zero_support_failures=sum(v['zero_probability_observed'] for v in vals))
    paired=[]
    for x in rr:
     ref=x['winner_benchmarks'].get('official_winner');mine=next((v for k,v in x['grades'][name]['markets'].items() if k.startswith('moneyline:')),None)
     if ref and mine and mine['conditional_brier'] is not None:paired.append(dict(event_id=x['event_id'],season=x['season'],week=x['week'],delta=mine['conditional_brier']-ref['conditional_brier']))
    metrics[name]=dict(markets=markets,paired_winner_brier_difference=week_block_ci(paired,'delta') if paired else None,margin_mae=sum(x['grades'][name]['margin_mae'] for x in rr)/len(rr) if rr else None,total_mae=sum(x['grades'][name]['total_mae'] for x in rr)/len(rr) if rr else None)
   weeks=len({(x['season'],x['week']) for x in g});returns=[x['hypothetical_return'] for x in g if x.get('hypothetical_return')]
   summary[sport][label]=dict(registered=len(r),primary_supported=sum(x['primary_supported'] for x in r),settled_primary=len(g),quote_supported=sum(bool(x['quote_data']) for x in r),injury_unidentified=sum(x['arms']['injury']['status']!='REGISTERED' for x in r),metrics=metrics,hypothetical=summarize_returns(returns),recommendation=readiness(len(g),weeks,sport),analysis='Pilot/descriptive; no repeated-look significance or production approval')
 lines=['# Project Craps — Beta v2 daily testing','',f'Updated: {clock().astimezone(ZoneInfo("America/New_York")).isoformat()}','', '| Sport | Window | Registered | Supported | Settled | Quote coverage |','|---|---|---:|---:|---:|---:|']
 for s,windows in summary.items():
  for h,v in windows.items():lines.append(f"| {s} | {h} | {v['registered']} | {v['primary_supported']} | {v['settled_primary']} | {v['quote_supported']} |")
 lines+=['','Original beta v1 records are preserved. Every v2 window is a separate immutable forecast. NFL Rams IDs are normalized to the canonical LA identifier.','', 'Comparators include the exact official NCAAB calibrated logistic winner model; score-kernel and independent Elo remain separately labeled. Full W/P/L, uncapped infinite-logloss flags, support failures and margins/totals are in latest-v2-status.json.','', '**Recommendation: keep testing.** These are prospective pilot records, not a demonstrated betting edge. Historical development results are separately labeled and are not fresh confirmation.','', 'NFL drive/play efficiency, identified injury values, current eligibility/role proof, validated 3PA/endgame/weather effects and authenticated exact-price coverage stay explicitly missing where unavailable. No invented player deductions or extra paid odds calls.','', 'Models and code are versioned. Daily research refits create a new bundle; official defaults, Sheets, original forecasts and wagers are unchanged.']
 (output/'V2_DAILY_REPORT.md').write_text('\n'.join(lines)+'\n');return dict(version=VERSION,sports=summary,production_approved=False)

def main():
 p=argparse.ArgumentParser();p.add_argument('--state',type=Path,default=STATE);p.add_argument('--output',type=Path,required=True);p.add_argument('--prepare',action='store_true');p.add_argument('--skip-context',action='store_true');a=p.parse_args();a.state.mkdir(parents=True,exist_ok=True);a.output.mkdir(parents=True,exist_ok=True)
 with (a.state/'run.lock').open('a') as f:
  fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
  if a.prepare:prepare(a.state,a.output)
  status=run(a.state,a.output,not a.skip_context)
 print(json.dumps({'new_forecasts':status['new_forecasts'],'source_errors':status['source_errors'],'quarantines':len(status['quarantines']),'journal':status['journal_anchor']},indent=2))
if __name__=='__main__':main()
