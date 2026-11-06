"""Additive NCAAF study registration and evidence coverage; never issues betting p."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
import hashlib,json,math
from pathlib import Path
from zoneinfo import ZoneInfo
import requests
from . import beta_daily
from .beta_v2.daily_entry import check_entry
from .beta_v2.runtime import load_bundle,STATE
CENTRAL=beta_daily.CENTRAL
STUDY=CENTRAL/'state/research-extensions/ncaaf-next-20261106'
BASE='https://site.api.espn.com/apis/site/v2/sports/football/college-football'
def sha(b):return hashlib.sha256(b).hexdigest()
def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def exclusive(p,b):
 p.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
 with p.open('xb') as f:f.write(b)
 p.chmod(0o600)
def freeze(p,b):
 if p.exists():
  if p.read_bytes()!=b:raise ValueError('frozen study drift')
 else:exclusive(p,b)
def replacement(rating,candidates,actual=None):
 if actual is not None:
  if not math.isfinite(actual):raise ValueError('invalid actual replacement')
  return actual
 usable=sorted([x for x in candidates if math.isfinite(x) and x<rating],reverse=True)[:3]
 return sum(usable)/len(usable) if usable else None

def register(state=STUDY):
 check_entry();load_bundle(STATE);beta_daily.official_check()
 policy=json.loads(Path(__file__).with_name('ncaaf_next_protocol.json').read_text())
 freeze(state/'protocol.json',canonical(policy))
 if not (state/'registration.json').exists():
  prior=[p.stem for p in (beta_daily.DEFAULT_STATE/'forecasts').glob('NCAAF-*.json')]
  exclusive(state/'registration.json',canonical(dict(registered_at=datetime.now(timezone.utc).isoformat(),protocol_sha256=sha(canonical(policy)),code_sha256=sha(Path(__file__).read_bytes()),prior_forecast_files=prior,prior_games_ineligible_for_confirmation=True)))
 rec=json.loads((state/'registration.json').read_text())
 if rec['code_sha256']!=sha(Path(__file__).read_bytes()):raise ValueError('study code drift')
 return policy,rec

def capture(url,state,now):
 slot=str(int(now.timestamp())//900);token=sha(url.encode());p=state/'sources'/slot/(token+'.receipt.json');raw=p.with_suffix('.body.json')
 if p.exists():
  r=json.loads(p.read_text())
  if r['status']=='CAPTURED' and sha(raw.read_bytes())!=r['sha256']:raise ValueError('source drift')
  return r,json.loads(raw.read_text()) if r['status']=='CAPTURED' else None
 r=dict(url=url,observed_at=now.isoformat(),published_at=None,independently_authenticated=False,status='ERROR_NO_RETRY')
 try:
  response=requests.get(url,timeout=15);response.raise_for_status();body=response.content;data=json.loads(body)
  r.update(status='CAPTURED',sha256=sha(body),observed_at=datetime.now(timezone.utc).isoformat());exclusive(raw,body)
 except Exception as exc:data=None;r['error_type']=type(exc).__name__
 exclusive(p,canonical(r));return r,data

def missing_inputs(event):
 return ['FBS_FBS_eligibility_not_independently_verified','QB_starter_and_availability_unverified','injury_report_publication_and_complete_coverage_unverified','replacement_roles_and_multiple_injury_workload_unverified','weather_at_forecast_cutoff_unverified','same_book_paired_price_authentication_missing','market_line_specific_validated_probabilities_missing','AP_poll_vintage_and_trap_inputs_unverified','momentum_input_vintages_unverified']

def run(output,state=STUDY):
 policy,registration=register(state);now=datetime.now(timezone.utc);events={};receipts=[]
 for i in range(3):
  date=(now.astimezone(ZoneInfo('America/New_York'))+timedelta(days=i)).strftime('%Y%m%d')
  r,d=capture(BASE+'/scoreboard?groups=80&limit=1000&dates='+date,state,now);receipts.append(r)
  if d:
   if len(d.get('events',[]))>=1000:raise ValueError('calendar truncated')
   for e in beta_daily.parse_events(d,'NCAAF',r['observed_at']):
    if e['status']=='pre' and 0<(beta_daily.instant(e['kickoff'])-now).total_seconds()<=48*3600:events[e['espn_event_id']]=e
 urls={BASE+'/injuries'}
 for e in events.values():
  urls.add(BASE+'/summary?event='+e['espn_event_id'])
  for side in ('home','away'):urls.add(BASE+'/teams/'+e[side+'_id']+'/roster')
 with ThreadPoolExecutor(max_workers=8) as pool:
  captures=list(pool.map(lambda u:capture(u,state,now),sorted(urls)))
 receipts.extend(r for r,d in captures)
 rows=[]
 for e in sorted(events.values(),key=lambda e:(e['kickoff'],e['espn_event_id'])):
  rows.append(dict(event_id=e['espn_event_id'],home=e['home'],away=e['away'],kickoff=e['kickoff'],status='PASS_INPUTS_UNVERIFIED',missing=missing_inputs(e),candidate_source_count=sum(str(e['espn_event_id']) in r['url'] or any('/teams/'+e[s+'_id']+'/' in r['url'] for s in ('home','away')) for r in receipts),approved_risk=0))
 forecasts=[beta_daily.integrity(p) for p in (beta_daily.DEFAULT_STATE/'forecasts').glob('NCAAF-*.json')]
 settlements=[beta_daily.integrity(p) for p in (beta_daily.DEFAULT_STATE/'settlements').glob('NCAAF-*.json')]
 result=dict(asof=now.isoformat(),protocol_sha256=registration['protocol_sha256'],registered_at=registration['registered_at'],games_next_48h=len(rows),candidate_sources=len(receipts),capture_failures=sum(r['status']!='CAPTURED' for r in receipts),authenticated_price_games=0,betting_supported_games=0,confirmation_games=0,pilot_status='NOT_STARTED: eligibility/authenticated market evidence not complete',legacy_v1_registered=len(forecasts),legacy_v1_settled=len(settlements),legacy_v1_pending=len(forecasts)-len(settlements),legacy_cohort='DESCRIPTIVE_PILOT_ONLY',events=rows,approved_risk=0,paid_requests=0,official_mutations=0)
 stamp=now.strftime('%Y%m%dT%H%M%S%fZ');exclusive(state/'runs'/(stamp+'.json'),canonical(dict(result,sources=receipts)))
 output.mkdir(parents=True,exist_ok=True);(output/'NCAAF_DECISION_STATUS.json').write_text(json.dumps(result,indent=2)+'\n')
 lines=['# NCAA football daily decision report','',f"As of {now.astimezone(ZoneInfo('America/New_York')).isoformat()}",'','**Research only. Approved risk: $0.**','',f"Next 48 hours: {len(rows)} candidate games; {len(receipts)} source receipts; {result['capture_failures']} retrieval failures.",f"Verified betting coverage: 0. Confirmation games: 0. Frozen v1: {len(forecasts)} registered, {len(settlements)} settled; descriptive pilot only.",'','Public summary/roster/injury/weather fields are source candidates. Retrieval time is not original publication authentication. No new model probabilities, bets or numerical injury effects issued.','', 'Next action: authenticate FBS eligibility, QB/availability and replacement roles, weather, exact paired prices, and line-specific probability inference. Pilot cannot begin until these inputs pass.','', '|Kickoff UTC|Game|Decision|','|---|---|---|']
 lines += [f"|{r['kickoff']}|{r['away']} at {r['home']}|PASS: pregame evidence incomplete|" for r in rows]
 lines+=['','Historical development findings: see ../ncaaf-next-20261106/DEVELOPMENT_DIAGNOSIS.md. Earlier folds remain examined; no historical result is confirmatory.']
 (output/'NCAAF_DECISION_REPORT.md').write_text('\n'.join(lines)+'\n');return result
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();r=run(a.output);print(json.dumps({k:v for k,v in r.items() if k!='events'},indent=2))
