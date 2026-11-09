"""Separately frozen NCAA football temperature-calibration research challenger.
No official model writes, tuning loops, market-informed predictions or live risk.
"""
import argparse
from collections import Counter,defaultdict
from datetime import datetime,timezone
import hashlib,json,math
from pathlib import Path
import numpy as np
from scipy.optimize import minimize_scalar
from .market_audit import checked,implied,odds_profit,settlement,instant
from .public_market_validation import append_shadow,digest,write_new,cluster_ci,summarize

VERSION='ncaaf-temperature-v1-20261109'
POLICY=dict(version=VERSION,fit_seasons=[2022,2023],examined_evaluation_seasons=[2024,2025],
    transformation='symmetric conditional logit temperature; no intercept; one nonnegative slope per market; push mass unchanged',
    objective='event-weighted conditional nonpush logistic loss + 0.5*(slope-1)^2',
    slope_bounds=[0,5],fit_endpoint_feature_epsilon=1e-12,endpoint_evaluation='preserve exact 0/1 when slope>0; slope zero maps conditional p to .5',
    primary_sides=['home','over'],event_weight='one per game per market; shared among its book/line rows',
    market_features=False,no_grid_or_candidate_selection=True,refit=False,confirmation_open=False,
    live_risk=0,coherent_joint_score_certificate=False,
    caveat='Temperature and bounds are unvalidated structural choices. Separate market probabilities do not certify a coherent joint score distribution. Examined history is not holdout.',
    prospective='new received-before-kickoff source captures after registration only; first event/book/market/line capture; all descriptive pilot excluded from future confirmation')


def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def calibrate(masses,slope):
    w,p,l=map(float,masses)
    if not all(math.isfinite(x) and x>=0 for x in (w,p,l)) or abs(w+p+l-1)>1e-10 or w+l<=0:
        raise ValueError('invalid probability vector')
    if not math.isfinite(slope) or slope<0 or slope>5:raise ValueError('invalid frozen slope')
    c=w/(w+l)
    if slope==0:z=.5
    elif c in (0,1):z=c
    else:
        v=slope*(math.log(c)-math.log1p(-c))
        z=1/(1+math.exp(-v)) if v>=0 else math.exp(v)/(1+math.exp(v))
    return [z*(1-p),p,(1-z)*(1-p)]


def fit_slope(prob,outcome,weight):
    p=np.asarray(prob);y=np.asarray(outcome);weights=np.asarray(weight)
    x=np.log(np.maximum(p,1e-12))-np.log(np.maximum(1-p,1e-12))
    objective=lambda b:float(np.sum(weights*(np.logaddexp(0,b*x)-y*b*x))+.5*(b-1)**2)
    result=minimize_scalar(objective,bounds=(0,5),method='bounded',options={'xatol':1e-10})
    if not result.success:raise ValueError('calibration fit failed')
    # Include exact constraint endpoints; deterministic optimization, no test-based selection.
    b=min([0.,float(result.x),5.],key=objective)
    return dict(slope=b,objective=objective(b),optimizer_success=True)


def proper(mass,outcome):
    index={1:0,0:1,-1:2}[outcome];p=mass[index]
    return dict(threeway_brier=sum((x-(i==index))**2 for i,x in enumerate(mass)),
                logloss=None if p==0 else -math.log(p),infinite_logloss=p==0)


def freeze_fit(state,archive,old_report,source_snapshot,output):
    from .beta_daily import official_check
    pointer,_=official_check();state=Path(state)
    if state.exists():raise ValueError('refuse refit or overwrite of existing calibration state')
    state.mkdir(parents=True,mode=0o700)
    write_new(state/'protocol.json',POLICY) # fixed before reading outcomes and fitting
    report=json.loads(Path(old_report).read_text())
    if digest(archive)!=report['joined_input_sha256']:raise ValueError('archive drift')
    for y,h in report['fold_model_sha256'].items():
        if digest(Path(archive).parent/f'fold-model-{y}.json')!=h:raise ValueError('saved fold drift')
    rows=[];rejections=Counter()
    for line in Path(archive).open():
        q=json.loads(line)
        if q['selection'] not in POLICY['primary_sides']:continue
        try:r=checked(q)
        except (ValueError,TypeError,KeyError) as exc:rejections[str(exc)]+=1;continue
        rows.append((q,r))
    coefficients={};fit_counts={}
    for market in ('moneyline','spread','total'):
        train=[(q,r) for q,r in rows if q['season'] in POLICY['fit_seasons'] and q['market']==market and r['outcome']]
        counts=Counter(q['event_id'] for q,r in train)
        coefficients[market]=fit_slope([r['model_conditional_win'] for q,r in train],
            [r['outcome']==1 for q,r in train],[1/counts[q['event_id']] for q,r in train])
        fit_counts[market]=dict(nonpush_rows=len(train),events=len(counts),observed_push_rows=sum(r['outcome']==0 for q,r in rows if q['market']==market and q['season'] in POLICY['fit_seasons']))
    model=dict(version=VERSION,coefficients=coefficients,fit_counts=fit_counts,source_sha256=digest(archive),
               parent_official_sha256=pointer['sports']['NCAAF']['sha256'],training_fold_sha256=report['fold_model_sha256'],
               fit_completed_at=datetime.now(timezone.utc).isoformat(),approval='RESEARCH_ONLY')
    write_new(state/'model.json',model)
    registration=dict(registered_at=datetime.now(timezone.utc).isoformat(),model_sha256=digest(state/'model.json'),
        protocol_sha256=digest(state/'protocol.json'),code_sha256={f:digest(Path(__file__).parent/f) for f in
        ['ncaaf_calibration.py','market_audit.py','public_market_validation.py','beta_daily.py']},confirmation_open=False,approved_risk=0)
    write_new(state/'registration.json',registration)
    # Historical evaluation occurs only after freezing; all of 2024-25 already examined.
    if digest(source_snapshot)!=report['source_snapshot_sha256']:raise ValueError('historical feature snapshot drift')
    from project_craps.common import unwrap
    from project_craps.features import historical_features
    features,_=historical_features([g for g in unwrap(json.loads(Path(source_snapshot).read_text()))['games'] if g['season']<=2025])
    elo={g['event_id']:1/(1+10**(-x[4]/400)) for g,x in features}
    evaluated=[]
    for q,r in rows:
        if q['season'] not in POLICY['examined_evaluation_seasons']:continue
        mass=calibrate([q['p_win'],q['p_push'],q['p_loss']],coefficients[q['market']]['slope'])
        qr=dict(q,p_win=mass[0],p_push=mass[1],p_loss=mass[2],model_version=VERSION)
        cr=checked(qr);cr['start_time_utc']=q['start_time_utc'];r['start_time_utc']=q['start_time_utc']
        evaluated.append((q,r,cr,proper([q['p_win'],q['p_push'],q['p_loss']],r['outcome']),proper(mass,r['outcome'])))
    results=[]
    for year in POLICY['examined_evaluation_seasons']:
        for market in ('moneyline','spread','total'):
            selected=[v for v in evaluated if v[0]['season']==year and v[0]['market']==market]
            counts=Counter(q['event_id'] for q,r,c,pr,pc in selected)
            weight=lambda q:1/counts[q['event_id']]
            mean=lambda f:sum(weight(v[0])*f(v) for v in selected)/len(counts) if counts else None
            non=[v for v in selected if v[1]['outcome']];nc=Counter(v[0]['event_id'] for v in non)
            def conditional(field):
                return sum((1/nc[v[0]['event_id']])*(field(v)-(v[1]['outcome']==1))**2 for v in non)/len(nc) if nc else None
            result=dict(season=year,market=market,events=len(counts),rows=len(selected),
                event_weighted_conditional_brier=dict(parent=conditional(lambda v:v[1]['model_conditional_win']),
                    challenger=conditional(lambda v:v[2]['model_conditional_win']),novig=conditional(lambda v:v[1]['no_vig_conditional_win']),
                    elo=conditional(lambda v:elo[v[0]['event_id']]) if market=='moneyline' else None),
                event_weighted_threeway_brier=dict(parent=mean(lambda v:v[3]['threeway_brier']),challenger=mean(lambda v:v[4]['threeway_brier'])),
                infinite_logloss_rows=dict(parent=sum(v[3]['infinite_logloss'] for v in selected),challenger=sum(v[4]['infinite_logloss'] for v in selected)),
                event_weighted_logloss=dict(parent=None if any(v[3]['infinite_logloss'] for v in selected) else mean(lambda v:v[3]['logloss']),challenger=None if any(v[4]['infinite_logloss'] for v in selected) else mean(lambda v:v[4]['logloss'])),
                parent_quote_weighted=summarize([v[1] for v in selected]),challenger_quote_weighted=summarize([v[2] for v in selected]))
            results.append(result)
    write_new(output,dict(version=VERSION,scope='EXAMINED_DEVELOPMENT_ONLY_NO_HOLDOUT',model=model,registration=registration,
        results=results,rejections=dict(rejections),transport_caveat='Historical rolling-fold input differs from official first-mean prospective point kernel. Future calibration transfer is unvalidated.',approved_risk=0))
    return model


def verify(state):
    from .beta_daily import official_check
    pointer,_=official_check();state=Path(state);reg=json.loads((state/'registration.json').read_text())
    if digest(state/'model.json')!=reg['model_sha256'] or digest(state/'protocol.json')!=reg['protocol_sha256']:raise ValueError('calibration artifact drift')
    for f,h in reg['code_sha256'].items():
        if digest(Path(__file__).parent/f)!=h:raise ValueError('calibration code drift: '+f)
    model=json.loads((state/'model.json').read_text())
    if model['parent_official_sha256']!=pointer['sports']['NCAAF']['sha256']:raise ValueError('official parent drift')
    return model,reg


def run_shadow(state,parent,output):
    model,reg=verify(state);state=Path(state);parent=Path(parent);now=datetime.now(timezone.utc)
    preg=json.loads((parent/'registration.json').read_text())
    for f,h in preg['code_sha256'].items():
        if digest(Path(__file__).parent/f)!=h:raise ValueError('parent shadow code drift')
    previous='0'*64;sources=[]
    for line in (parent/'journal.jsonl').read_text().splitlines():
        entry=json.loads(line)
        if entry['previous']!=previous or digest(parent/entry['file'])!=entry['sha256']:raise ValueError('parent shadow journal drift')
        previous=hashlib.sha256(line.encode()).hexdigest();sources.append((entry,json.loads((parent/entry['file']).read_text())))
    existing=set();oldrows=[];capturestate=state/'captures'
    if (capturestate/'journal.jsonl').exists():
        previous='0'*64
        for line in (capturestate/'journal.jsonl').read_text().splitlines():
            j=json.loads(line)
            if j['previous']!=previous or digest(capturestate/j['file'])!=j['sha256']:raise ValueError('challenger capture drift')
            previous=hashlib.sha256(line.encode()).hexdigest()
            for row in json.loads((capturestate/j['file']).read_text())['rows']:
                existing.add(row['key']);oldrows.append(row)
    rows=[];refusals=Counter()
    for entry,payload in sources:
        if instant(payload['observed_at'])<instant(reg['registered_at']):continue
        for e in payload['events']:
            if 'error' in e:refusals['parent_source_failure']+=1;continue
            gid=e['event_id'];identity=e['identity']
            if gid=='401862818':refusals['preserved_kickoff_quarantine']+=1;continue
            received=instant(e['received_at'])
            if received<instant(reg['registered_at']) or received>=instant(identity['kickoff']) or now>=instant(identity['kickoff']):continue
            if (now-received).total_seconds()>3600:refusals['source_older_than_hour']+=1;continue
            for q in e['quotes']:
                key=hashlib.sha256(canonical([gid,q['book'],q['market'],q['selection'],q['line']])).hexdigest()
                if key in existing:continue
                if 'derived_point_kernel_WPL' not in q:refusals['missing_parent_probability']+=1;continue
                mass=calibrate(q['derived_point_kernel_WPL'],model['coefficients'][q['market']]['slope'])
                a=implied(q['american_odds']);b=implied(q['opposing_american_odds'])
                row=dict(key=key,event_id=gid,identity=identity,neutral=bool(e['raw_source']['header']['competitions'][0].get('neutralSite',False)),
                    market=q['market'],selection=q['selection'],line=q['line'],book=q['book'],american_odds=q['american_odds'],opposing_american_odds=q['opposing_american_odds'],
                    observed_at=e['received_at'],issued_at=now.isoformat(),quote_original_update=None,scope=q['scope'],
                    parent_WPL=q['derived_point_kernel_WPL'],challenger_WPL=mass,novig_conditional=a/(a+b),elo=None,
                    model_sha256=reg['model_sha256'],parent_capture_sha256=entry['sha256'],parent_forecast_sha256=e['parent_record_sha256'],feature_cutoff=e['feature_cutoff'],
                    cohort='DESCRIPTIVE_PILOT_ONLY',confirmation_eligible=False,approved_risk=0,
                    gaps=['unvalidated historical-to-live probability transport','old parent feature cutoff','original quote time/scope/jurisdiction unauthenticated','QB/roster/workload/weather evidence incomplete','independent future Elo unavailable'])
                for name,prob in [('parent',row['parent_WPL']),('challenger',mass)]:
                    threshold=.025 if q['market']=='spread' else .030
                    row[name+'_hypothetical_selected']=(prob[0]/(1-prob[1])-a>=threshold and prob[0]*odds_profit(q['american_odds'])-prob[2]>0)
                rows.append(row);existing.add(key)
    append_shadow(capturestate,dict(observed_at=now.isoformat(),rows=rows,refusals=dict(refusals),approved_risk=0))
    # Append exact-identity provider-final grades, never revise old forecasts or grades.
    grade_state=state/'grades';oldgrades={};quarantined=set()
    if (grade_state/'journal.jsonl').exists():
        previous='0'*64
        for line in (grade_state/'journal.jsonl').read_text().splitlines():
            j=json.loads(line)
            if j['previous']!=previous or digest(grade_state/j['file'])!=j['sha256']:raise ValueError('grade journal drift')
            previous=hashlib.sha256(line.encode()).hexdigest();g=json.loads((grade_state/j['file']).read_text())
            for grade in g['grades']:oldgrades[grade['key']]=grade
            quarantined.update(x['event_id'] for x in g['quarantines'])
    import requests
    newgrades=[];quarantines=[];failures=[];finalsources=[]
    ready=defaultdict(list)
    for row in oldrows+rows:
        if instant(row['identity']['kickoff'])<=now:ready[row['event_id']].append(row)
    for gid,rs in ready.items():
        if gid in quarantined:continue
        try:
            response=requests.get(f'https://site.api.espn.com/apis/site/v2/sports/football/college-football/summary?event={gid}',timeout=20);response.raise_for_status();data=response.json()
            c=data['header']['competitions'][0];sides={x['homeAway']:x for x in c['competitors']}
            if not c['status']['type'].get('completed'):continue
            finalsources.append(dict(event_id=gid,raw_source=data,source_sha256=hashlib.sha256(response.content).hexdigest(),received_at=datetime.now(timezone.utc).isoformat()))
            for row in rs:
                if str(data['header']['id'])!=gid or any(str(sides[s]['team']['id'])!=row['identity'][s+'_id'] for s in ('home','away')) or instant(c['date'])!=instant(row['identity']['kickoff']) or bool(c.get('neutralSite',False))!=row['neutral']:
                    quarantines.append(dict(event_id=gid,reason='identity/kickoff/neutral revision'));continue
                h,a=int(sides['home']['score']),int(sides['away']['score'])
                if h==a or min(h,a)<0:raise ValueError('invalid college final score')
                outcome=settlement(dict(row,home_score=h,away_score=a))
                if row['key'] in oldgrades:
                    old=oldgrades[row['key']]
                    if (h,a)!=(old['home_score'],old['away_score']):quarantines.append(dict(event_id=gid,reason='score revision; prior grade preserved'))
                    continue
                payout=odds_profit(row['american_odds']);rawprofit=payout if outcome==1 else -1 if outcome==-1 else 0
                grade=dict(key=row['key'],event_id=gid,market=row['market'],home_score=h,away_score=a,outcome=outcome,
                    parent=proper(row['parent_WPL'],outcome),challenger=proper(row['challenger_WPL'],outcome),
                    novig_conditional_brier=None if not outcome else (row['novig_conditional']-(outcome==1))**2,
                    parent_hypothetical_profit=rawprofit if row['parent_hypothetical_selected'] else 0,challenger_hypothetical_profit=rawprofit if row['challenger_hypothetical_selected'] else 0,source_sha256=finalsources[-1]['source_sha256'],scope_assumption=row['scope'],
                    independently_authenticated_final=False,approved_risk=0)
                newgrades.append(grade)
        except (requests.RequestException,ValueError,KeyError,TypeError) as exc:failures.append(dict(event_id=gid,error=type(exc).__name__))
    append_shadow(grade_state,dict(observed_at=now.isoformat(),grades=newgrades,quarantines=quarantines,source_failures=failures,sources=finalsources,approved_risk=0))
    quarantined.update(q['event_id'] for q in quarantines)
    allgrades={**oldgrades,**{g['key']:g for g in newgrades}};rowmap={r['key']:r for r in oldrows+rows};paired=[]
    for market in ('moneyline','spread','total'):
        gs=[g for g in allgrades.values() if g['market']==market and g['event_id'] not in quarantined]
        bygame=Counter(g['event_id'] for g in gs)
        mean=lambda f:sum(f(g)/bygame[g['event_id']] for g in gs)/len(bygame) if bygame else None
        result=dict(market=market,settled_records=len(gs),settled_games=len(bygame),
            parent_threeway_brier=mean(lambda g:g['parent']['threeway_brier']),challenger_threeway_brier=mean(lambda g:g['challenger']['threeway_brier']),
            parent_infinite_logloss=sum(g['parent']['infinite_logloss'] for g in gs),challenger_infinite_logloss=sum(g['challenger']['infinite_logloss'] for g in gs),
            elo_brier=None)
        for name in ('parent','challenger'):
            selected=[g for g in gs if rowmap[g['key']][name+'_hypothetical_selected']]
            result[name+'_hypothetical_selected']=len(selected)
            result[name+'_hypothetical_roi']=sum(g[name+'_hypothetical_profit'] for g in selected)/len(selected) if selected else None
        paired.append(result)
    status=dict(asof=now.isoformat(),version=VERSION,new_rows=len(rows),registered_rows=len(oldrows)+len(rows),
        games=len({r['event_id'] for r in oldrows+rows}),new_grades=len(newgrades),total_grades=len(oldgrades)+len(newgrades),
        refusals=dict(refusals),paired_results=paired,quarantines=quarantines,quarantined_event_ids=sorted(quarantined),source_failures=failures,confirmation_open=False,approved_risk=0)
    write_new(output,status);return status


def main():
    parser=argparse.ArgumentParser();subs=parser.add_subparsers(dest='mode',required=True)
    p=subs.add_parser('fit');p.add_argument('--state',type=Path,required=True);p.add_argument('--archive',required=True);p.add_argument('--original-report',required=True);p.add_argument('--source-snapshot',required=True);p.add_argument('--output',type=Path,required=True)
    p=subs.add_parser('run');p.add_argument('--state',type=Path,required=True);p.add_argument('--parent',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=parser.parse_args()
    if a.mode=='fit':r=freeze_fit(a.state,a.archive,a.original_report,a.source_snapshot,a.output)
    else:r=run_shadow(a.state,a.parent,a.output)
    print(json.dumps(r,indent=2))
if __name__=='__main__':main()
