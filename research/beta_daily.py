"""Read-only official references, additive beta forecasts and append-only grading."""
import argparse
import fcntl
import hashlib
import html
import json
import math
from collections import Counter,defaultdict
from datetime import datetime,timedelta,timezone
from pathlib import Path
import requests
from .validation_v2 import canonical,sha,instant
from .probability_v2 import weighted_outcome_masses,proper_scores,week_block_ci

SPORTS={'NCAAF':'football/college-football','NFL':'football/nfl','NCAAB':'basketball/mens-college-basketball'}
CENTRAL=Path('/Users/wadeholland/Documents/Codex/Project-Craps')
DEFAULT_STATE=CENTRAL/'state/research-extensions/daily-challengers-v1-20261105'


def create(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as f:f.write(canonical(value))
    path.chmod(0o600)


def official_check():
    p=json.loads((CENTRAL/'OFFICIAL_MODELS.json').read_text());mf=Path(p['active_release_manifest'])
    if sha(mf.read_bytes())!=p['active_release_manifest_sha256']:raise ValueError('release manifest drift')
    m=json.loads(mf.read_text());rt=json.loads((CENTRAL/'state/ACTIVE_RUNTIME.json').read_text());active=json.loads(Path(rt['active_runtime_release']).read_text())
    for s,v in p['sports'].items():
        if sha(Path(v['path']).read_bytes())!=v['sha256'] or active['sports'][s]['sha256']!=v['sha256']:raise ValueError('official model/runtime drift: '+s)
    for f,h in m['code_sha256'].items():
        if sha(Path(f).read_bytes())!=h:raise ValueError('official code drift: '+f)
    return p,rt


def reference_digest(record):
    return sha(json.dumps({k:v for k,v in record.items() if k!='record_sha256'},sort_keys=True,default=str,allow_nan=False).encode())


def reference_scores(record,artifact):
    """NEW private point-kernel inference. Never backfill original win probabilities."""
    m=record['predicted_home_margin_research_only'];t=record['predicted_total_research_only']
    if any(not isinstance(x,(float,int)) or not math.isfinite(x) for x in (m,t)):raise ValueError('invalid point reference')
    result=[]
    for dm,dt in artifact['residual_pairs']:
        h=max(0,math.floor((t+dt+m+dm)/2+.5));a=max(0,math.floor((t+dt-m-dm)/2+.5))
        if record['sport']!='NFL' and h==a:continue
        result.append((h,a))
    if not result:raise ValueError('empty reference support')
    return result


def pair_masses(sport,candidate):
    out={'moneyline:home':weighted_outcome_masses(candidate,'moneyline','home')}
    total=140 if sport=='NCAAB' else 55 if sport=='NCAAF' else 45
    for market,selection,lines in [('spread','home',[-3.,-3.5,-7.,-7.5]),('total','over',[float(total),total+.5])]:
        for line in lines:out[f'{market}:{selection}:{line}']=weighted_outcome_masses(candidate,market,selection,line)
    return out


def normalize_nfl(abbrev):
    return {'WSH':'WAS','LA':'LAR'}.get(abbrev,abbrev)


def parse_events(data,sport,observed):
    events=[]
    for e in data.get('events',[]):
        for c in e.get('competitions',[]):
            teams={x['homeAway']:x for x in c.get('competitors',[])}
            if set(teams)!={'home','away'}:continue
            ids={side:(normalize_nfl(x['team']['abbreviation']) if sport=='NFL' else str(x['team']['id'])) for side,x in teams.items()}
            row=dict(sport=sport,espn_event_id=str(e['id']),kickoff=c['date'],home_id=ids['home'],away_id=ids['away'],
                home_espn_id=str(teams['home']['team']['id']),away_espn_id=str(teams['away']['team']['id']),
                home=teams['home']['team'].get('displayName',ids['home']),away=teams['away']['team'].get('displayName',ids['away']),
                neutral=c.get('neutralSite',False if sport=='NFL' else None),observed_at=observed,
                status='FINAL' if c.get('status',{}).get('type',{}).get('completed') else c.get('status',{}).get('type',{}).get('state','unknown'),
                season=e.get('season',{}).get('year',data.get('season',{}).get('year')))
            if row['status']=='FINAL':
                scores=[]
                for side in ('home','away'):
                    v=float(teams[side]['score'])
                    if not math.isfinite(v) or v<0 or not v.is_integer():raise ValueError('invalid final score')
                    scores.append(int(v))
                row.update(home_score=scores[0],away_score=scores[1])
                if sport!='NFL' and scores[0]==scores[1]:row['status']='INVALID_FINAL_TIE'
            events.append(row)
    return events


def capture_calendar(sport,state,now,days=7):
    # ESPN currently accepts individual dates, not date ranges. Capture each day once.
    from concurrent.futures import ThreadPoolExecutor
    url='https://site.api.espn.com/apis/site/v2/sports/'+SPORTS[sport]+'/scoreboard'
    dates=[(now+timedelta(days=i)).strftime('%Y%m%d') for i in range(-14,days+1)]
    folder=state/'sources'/sport;folder.mkdir(parents=True,exist_ok=True)
    def fetch(date):
        params=dict(dates=date,limit=1000)
        if sport in ('NCAAF','NCAAB'):params['groups']=80 if sport=='NCAAF' else 50
        try:
            r=requests.get(url,params=params,timeout=30);r.raise_for_status();data=r.json();captured=datetime.now(timezone.utc).isoformat();digest=sha(r.content)
            body=folder/(digest+'.json')
            # Identical bodies across dates/requests are immutable and may be reused.
            try:
                with body.open('xb') as f:f.write(r.content)
                body.chmod(0o600)
            except FileExistsError:
                if sha(body.read_bytes())!=digest:raise ValueError('calendar source collision')
            rec=dict(url=r.url,sha256=digest,observed_at=captured,original_publication_verified=False)
            create(folder/(sha(canonical(rec))+'.receipt.json'),rec)
            if len(data.get('events',[]))>=1000:raise ValueError('calendar may be truncated at1000events')
            events=parse_events(data,sport,captured)
            for e in events:e['source_sha256']=digest
            return events,rec,None
        except Exception as exc:return [],None,dict(sport=sport,date=date,error=str(exc))
    events={};receipts=[];failures=[]
    with ThreadPoolExecutor(max_workers=8) as executor:
        results=list(executor.map(fetch,dates))
    for es,rec,fail in results:
        if fail:failures.append(fail);continue
        receipts.append(rec)
        for e in es:
            key=e['espn_event_id'];old=events.get(key)
            if old and (old['home_id'],old['away_id'],old['kickoff'])!=(e['home_id'],e['away_id'],e['kickoff']):raise ValueError('calendar identity revision across daily captures')
            if old is None or e['observed_at']>old['observed_at']:events[key]=e
    return list(events.values()),dict(sha256=sha(canonical(receipts)),daily_source_receipts=receipts,failures=failures,original_publication_verified=False)


def match_reference(record,events):
    candidates=[e for e in events if e['home_id']==record['home_id'] and e['away_id']==record['away_id']]
    if record['sport']!='NFL':candidates=[e for e in candidates if e['espn_event_id']==record['event_id']]
    exact=[e for e in candidates if instant(e['kickoff'])==instant(record['kickoff'])]
    if len(exact)==1:return exact[0],None
    return None,'identity_or_kickoff_revision' if candidates else 'fresh_fixture_not_found'


def integrity(path):
    w=json.loads(path.read_text())
    if sha(canonical(w['payload']))!=w['sha256']:raise ValueError('beta record hash mismatch')
    return w['payload']


def save_forecast(path,payload):
    create(path,dict(payload=payload,sha256=sha(canonical(payload))))


def settle(record,event):
    if instant(record['issued_at'])>=instant(event['kickoff']):raise ValueError('forecast not pregame')
    if (record['identity']['home_id'],record['identity']['away_id'],instant(record['identity']['kickoff']))!=(event['home_id'],event['away_id'],instant(event['kickoff'])):raise ValueError('settlement identity drift')
    if event['status']!='FINAL':return None
    if instant(event['observed_at'])<=instant(event['kickoff']):raise ValueError('final observed before kickoff')
    margin=event['home_score']-event['away_score'];total=event['home_score']+event['away_score'];grades={}
    for arm,pred in record['arms'].items():
        if pred.get('status')!='REGISTERED':continue
        metrics={}
        for key,masses in pred['masses'].items():
            parts=key.split(':');value=margin if parts[0]=='moneyline' else margin+float(parts[2]) if parts[0]=='spread' else total-float(parts[2])
            outcome=1 if value>0 else -1 if value<0 else 0
            sc=proper_scores(masses,outcome)
            # JSON cannot truthfully encode infinity as a finite score.
            metrics[key]={k:(v if v is None or math.isfinite(v) else None) for k,v in sc.items()}
            metrics[key]['zero_probability_observed']=not math.isfinite(sc['threeway_logloss'])
        grades[arm]=dict(metrics=metrics,margin_absolute_error=abs(pred['point_margin']-margin),total_absolute_error=abs(pred['point_total']-total))
    return dict(event_id=record['event_id'],sport=record['sport'],forecast_sha256=sha(canonical(record)),result_source_sha256=event['source_sha256'],observed_at=event['observed_at'],home_score=event['home_score'],away_score=event['away_score'],week=instant(event['kickoff']).isocalendar()[1],season=event['season'],grades=grades,elo_conditional_brier=(record['independent_elo_reference']-int(margin>0))**2 if margin!=0 and record.get('independent_elo_reference') is not None else None,official_risk=0,official_pnl=0)


def arm(scores,sport,point=None):
    if isinstance(scores,dict):candidate=scores
    else:candidate=dict(scores=scores,weights=[1/len(scores)]*len(scores))
    if sport!='NFL':
        pairs=[(s,w) for s,w in zip(candidate['scores'],candidate['weights']) if s[0]!=s[1]]
        if not pairs:raise ValueError('non-tie support unavailable')
        total=sum(w for s,w in pairs);candidate=dict(scores=[s for s,w in pairs],weights=[w/total for s,w in pairs])
    m=sum((h-a)*w for (h,a),w in zip(candidate['scores'],candidate['weights']));t=sum((h+a)*w for (h,a),w in zip(candidate['scores'],candidate['weights']))
    return dict(status='REGISTERED',masses=pair_masses(sport,candidate),point_margin=m,point_total=t,raw_point=point)


def verify_journal(state):
    journal=state/'journal.jsonl';previous='GENESIS';seen=set();seq=0
    if journal.exists():
        for line in journal.read_text().splitlines():
            entry=json.loads(line);expected=entry.pop('entry_sha256')
            if entry['seq']!=seq+1 or entry['previous']!=previous or sha(canonical(entry))!=expected:raise ValueError('beta journal corruption')
            path=state/entry['path']
            if not path.exists() or sha(path.read_bytes())!=entry['file_sha256']:raise ValueError('beta journal record missing or changed')
            seen.add(entry['path']);previous=expected;seq+=1
    actual={str(p.relative_to(state)) for folder in ('forecasts','settlements') for p in (state/folder).glob('*.json')}
    if actual!=seen:raise ValueError('unmanaged beta records or journal truncation')
    anchor=dict(count=seq,head=previous)
    ap=state/'journal-anchor.json'
    if ap.exists() and json.loads(ap.read_text())!=anchor:raise ValueError('beta journal anchor mismatch')
    if seq and not ap.exists():raise ValueError('beta journal anchor missing')
    return anchor


def journaled_save(state,path,payload):
    anchor=verify_journal(state);save_forecast(path,payload)
    entry=dict(seq=anchor['count']+1,previous=anchor['head'],path=str(path.relative_to(state)),file_sha256=sha(path.read_bytes()))
    entry['entry_sha256']=sha(canonical(entry))
    with (state/'journal.jsonl').open('ab') as f:f.write(canonical(entry)+b'\n')
    temp=state/'journal-anchor.tmp';temp.write_bytes(canonical(dict(count=entry['seq'],head=entry['entry_sha256'])))
    temp.replace(state/'journal-anchor.json')


def run(state,output,*,collect_availability=True):
    from .daily_calibration import apply as apply_calibration
    from .daily_efficiency import predict as predict_efficiency
    from .daily_availability import collect,adjust
    pointer,runtime=official_check();state=Path(state);output=Path(output);output.mkdir(parents=True,exist_ok=True)
    verify_journal(state)
    now=datetime.now(timezone.utc);manifest=json.loads((state/'manifest.json').read_text())
    for f,h in manifest['files'].items():
        if sha(Path(f).read_bytes())!=h:raise ValueError('beta implementation/artifact drift: '+f)
    if manifest['official_model_hashes']!={s:pointer['sports'][s]['sha256'] for s in SPORTS}:raise ValueError('beta basehash drift')
    events={};sources={};errors=[]
    for sport in SPORTS:
        try:
            events[sport],sources[sport]=capture_calendar(sport,state,now)
            errors.extend(dict(x,stage='calendar_day') for x in sources[sport].get('failures',[]))
        except Exception as exc:events[sport]=[];errors.append(dict(sport=sport,stage='calendar',error=str(exc)))
    forecasts=state/'forecasts';settlements=state/'settlements';quarantines=[];new=Counter();arm_counts=Counter();refs=Path(runtime['first_forecast_registry'])
    artifacts={}
    for s in SPORTS:
        wrapped=json.loads(Path(pointer['sports'][s]['path']).read_text());artifacts[s]=wrapped.get('payload',wrapped)
    for sport in SPORTS:
        for path in sorted(refs.glob(sport+'-*.json')):
            r=json.loads(path.read_text())
            if reference_digest(r)!=r.get('record_sha256'):raise ValueError('official reference record drift: '+str(path))
            if r['model_sha256']!=pointer['sports'][sport]['sha256']:continue
            if instant(r['kickoff'])<=datetime.now(timezone.utc) or instant(r['kickoff'])>now+timedelta(days=7):continue
            event,reason=match_reference(r,events[sport])
            if reason:quarantines.append(dict(sport=sport,event_id=r['event_id'],reason=reason));continue
            key=sport+'-'+str(r['event_id'])+'-'+manifest['version'];target=forecasts/(key+'.json')
            if target.exists():integrity(target);continue
            event=dict(event,event_id=r['event_id'])
            scores=reference_scores(r,artifacts[sport]);arms={'point_kernel_reference':arm(scores,sport)}
            missing=[]
            cp=state/'calibration'/(sport+'.json');ep=state/'efficiency'/(sport+'.json')
            if cp.exists():
                ca=json.loads(cp.read_text())
                if ca['sport']!=sport or instant(ca['fit_cutoff'])>=datetime.now(timezone.utc):raise ValueError('calibration sport/time mismatch')
                arms['calibration']=arm(apply_calibration(scores,ca),sport)
            else:arms['calibration']=dict(status='NOT_COMPUTED',reason='fitted_artifact_missing')
            if ep.exists():
                ea=json.loads(ep.read_text())
                if ea['sport']!=sport or instant(ea['cutoff'])>=datetime.now(timezone.utc):raise ValueError('efficiency sport/time mismatch')
                eff=predict_efficiency(ea,event) if type(event['neutral']) is bool else {'status':'NEUTRAL_SITE_UNVERIFIED'}
                if eff.get('paired_score_samples'):
                    arms['opponent_efficiency']=arm(eff['paired_score_samples'],sport,eff.get('point_scores'))
                    arms['opponent_efficiency']['mode']=eff['mode'];arms['opponent_efficiency']['expected_possessions']=eff['expected_possessions']
                else:arms['opponent_efficiency']=dict(status='NOT_COMPUTED',reason=eff.get('status'))
            else:arms['opponent_efficiency']=dict(status='NOT_COMPUTED',reason='fitted_artifact_missing')
            availability=None
            if collect_availability and instant(event['kickoff'])<datetime.now(timezone.utc)+timedelta(hours=24):
                deadline=min(instant(event['kickoff'])-timedelta(seconds=5),datetime.now(timezone.utc)+timedelta(minutes=15))
                availability=collect(sport,event,deadline.isoformat(),state/'availability')
            else:missing.append('availability collection deferred to within24hours')
            arms['injury']=dict(status='NOT_COMPUTED',reason='identified_sport_specific_injury_values_and_complete_role_inputs_required')
            if availability:
                model={'frozen_candidate_path':str(CENTRAL/'state/research-extensions/injury-shock-v1-20261105/candidate-frozen.json')} if sport=='NCAAF' else None
                result=adjust(r['predicted_home_margin_research_only'],availability,model)
                arms['injury']['diagnostic']=result
                missing.extend(availability['issueflags'])
            elo=None
            if sport=='NCAAB':elo=r.get('history_audit',{}).get('elo_probability')
            else:
                st=artifacts[sport]['state'];h=st.get(r['home_id']);a=st.get(r['away_id'])
                if h and a:elo=1/(1+10**((a['elo']-h['elo'])/400))
            issued=datetime.now(timezone.utc)
            if issued>=instant(event['kickoff']):quarantines.append(dict(sport=sport,event_id=r['event_id'],reason='started_during_collection'));continue
            if availability and any(instant(x['observed_at'])>issued for x in availability['sources']):raise ValueError('availability after issuance')
            record=dict(version=manifest['version'],sport=sport,event_id=r['event_id'],identity={k:event[k] for k in ('home_id','away_id','home','away','kickoff','espn_event_id')},
                issued_at=issued.isoformat(),source_snapshot=sources[sport],official_reference_file=str(path),official_reference_sha256=r['record_sha256'],official_reference_issued_at=r['issued_at'],
                official_model_sha256=r['model_sha256'],manifest_sha256=sha(canonical(manifest)),arms=arms,missing_inputs=missing,
                note='New private research inference at issuance, not recovered or backfilled original probabilities',source_authentication_verified=False,
                independent_elo_reference=elo,elo_note='Frozen release state / archived pregame independent Elo, not a new fitted challenger',
                betting_approved=False,approved_risk=0)
            journaled_save(state,target,record);new[sport]+=1
            for name,v in arms.items():
                if v['status']=='REGISTERED':arm_counts[sport+':'+name]+=1
    # Grade only our immutable prospective records, never an original forecast or wager.
    for path in sorted(forecasts.glob('*.json')):
        record=integrity(path);s=record['sport'];r=dict(record['identity'],sport=s,event_id=record['event_id']);event,reason=match_reference(r,events[s])
        if reason:quarantines.append(dict(sport=s,event_id=r['event_id'],reason=reason));continue
        if event['status']!='FINAL':continue
        grade=settle(record,event);target=settlements/path.name
        if target.exists():
            old=integrity(target)
            if (old['home_score'],old['away_score'])!=(grade['home_score'],grade['away_score']):quarantines.append(dict(sport=s,event_id=r['event_id'],reason='result_revision_preserved_original'))
            continue
        journaled_save(state,target,grade)
    status=report(state,output,errors,quarantines)
    status.update(new_forecasts=dict(new),new_registered_arms=dict(arm_counts),run_at=datetime.now(timezone.utc).isoformat(),paid_requests=0,official_mutations=0)
    runid=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');create(state/'runs'/(runid+'.json'),status)
    (output/'latest-status.json').write_text(json.dumps(status,indent=2))
    return status


def report(state,output,errors,quarantines):
    summaries={};settled=[integrity(p) for p in (state/'settlements').glob('*.json')];records=[integrity(p) for p in (state/'forecasts').glob('*.json')]
    for sport in SPORTS:
        rs=[r for r in records if r['sport']==sport]
        supported_ids={r['event_id'] for r in rs if r['arms'].get('opponent_efficiency',{}).get('status')=='REGISTERED'}
        all_gs=[g for g in settled if g['sport']==sport];gs=[g for g in all_gs if g['event_id'] in supported_ids];metrics={}
        for name in ('point_kernel_reference','calibration','opponent_efficiency','injury'):
            chosen=[g for g in gs if name in g['grades']]
            vals=[];deltas=[]
            for g in chosen:
                v=g['grades'][name]['metrics']['moneyline:home']['conditional_brier'];b=g['grades']['point_kernel_reference']['metrics']['moneyline:home']['conditional_brier']
                if v is not None and b is not None:
                    vals.append(v);deltas.append(dict(event_id=g['event_id'],season=g['season'],week=g['week'],difference=v-b))
            per_market={}
            for key in (chosen[0]['grades'][name]['metrics'] if chosen else []):
                values=[g['grades'][name]['metrics'][key]['threeway_brier'] for g in chosen]
                per_market[key]=dict(games=len(values),threeway_brier=sum(values)/len(values) if values else None)
            metrics[name]=dict(per_market=per_market,settled=len(chosen),conditional_winner_brier=sum(vals)/len(vals) if vals else None,
                margin_mae=sum(g['grades'][name]['margin_absolute_error'] for g in chosen)/len(chosen) if chosen else None,
                total_mae=sum(g['grades'][name]['total_absolute_error'] for g in chosen)/len(chosen) if chosen else None,
                paired_difference=week_block_ci(deltas,'difference') if deltas else None,
                forecast_records=sum(r['arms'].get(name,{}).get('status')=='REGISTERED' for r in rs))
        ev=[g['elo_conditional_brier'] for g in gs if g.get('elo_conditional_brier') is not None]
        summaries[sport]=dict(elo_conditional_brier=sum(ev)/len(ev) if ev else None,registered_events=len(rs),primary_supported_events=len(supported_ids),outside_common_support=len(rs)-len(supported_ids),settled_events=len(all_gs),primary_settled_events=len(gs),pending_events=len(rs)-len(all_gs),arms=metrics,
            recommendation='KEEP_TESTING: no automatic changes; inspect coverage, proper scores, independent authentication and adequate future week blocks',
            market_benchmark='NOT_COMPUTED: authenticated matched beta-time prices missing',hypothetical_roi=None,roi_reason='No validated fixed-price ticket cohort',
            injury_status='Unidentified coefficients or verified pregame role/value inputs missing')
    lines=['# Project Craps — Beta Model Lab','',f'Updated: {datetime.now(timezone.utc).isoformat()}','',
        'Daily testing of NCAAF, NFL and NCAA men’s basketball. All challengers are research-only; official models and wagers stay frozen.','',
        '| Sport | Registered games | Settled | Pending | Calibration Brier | Efficiency Brier |','|---|---:|---:|---:|---:|---:|']
    f=lambda v:'—' if v is None else f'{v:.4f}'
    for s,v in summaries.items():lines.append(f"| {s} | {v['registered_events']} | {v['settled_events']} | {v['pending_events']} | {f(v['arms']['calibration']['conditional_winner_brier'])} | {f(v['arms']['opponent_efficiency']['conditional_winner_brier'])} |")
    lines+=['','Brier: lower is better. A dash means no usable settled observations. Detailed per-market W/P/L scores remain in immutable private grading records.','',
        '**Recommended changes today:** Keep testing frozen challengers. No production change is supported solely by a daily win/loss result. Review weekly using paired event-level losses and enough independent time blocks.','',
        '**Coverage:** Injury arms remain unavailable unless independently trained sport-specific values and verified workloads exist. Football efficiency is an explicitly labeled opponent-adjusted full-score fallback; football possessions are not invented. Basketball uses box-estimated possessions and pace. The point-kernel reference uses official raw means with paired residuals, and is not a recovery of original moneyline probabilities.','',
        f'Quarantined fixture/result checks this run: {len(quarantines)}. Source/runtime failures: {len(errors)}.','',
        'Primary comparisons use the common supported-team cohort (efficiency arm available), fixed before outcomes. Other forecasts remain retained outside that comparison; team eligibility still requires independent certification.', '',
        'Matched no-vig, executable ROI and CLV remain unavailable without authenticated prices at each beta forecast cutoff. Private receipts preserve missingness. No paid API calls occur in this beta runner.']
    text='\n'.join(lines)+'\n';(output/'DAILY_REPORT.md').write_text(text)
    (output/'dashboard.html').write_text('<!doctype html><meta charset="utf-8"><title>Project Craps — Beta Model Lab</title><style>body{font:16px system-ui;max-width:1100px;margin:40px auto;background:#111827;color:#e5e7eb;padding:20px}pre{white-space:pre-wrap;line-height:1.6}h1{color:#5eead4}</style><h1>Project Craps — Beta Model Lab</h1><pre>'+html.escape(text)+'</pre>')
    return dict(sports=summaries,source_errors=errors,quarantines=quarantines,betting_approved=False)


def main():
    p=argparse.ArgumentParser();p.add_argument('--state',type=Path,default=DEFAULT_STATE);p.add_argument('--output',type=Path,required=True);p.add_argument('--skip-availability',action='store_true');a=p.parse_args();a.state.mkdir(parents=True,exist_ok=True)
    with (a.state/'run.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        result=run(a.state,a.output,collect_availability=not a.skip_availability)
    print(json.dumps({k:v for k,v in result.items() if k not in ('quarantines',)},indent=2))

if __name__=='__main__':main()
