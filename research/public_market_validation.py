"""Additive exploratory public-quote QA, saved-forecast replay and append-only shadow.
Never modifies model artifacts, forecasts, wagers or production gates.
"""
import argparse
import csv
import fcntl
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
from .market_audit import checked, implied, instant, metrics, odds_profit, settlement


def digest(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def write_new(p, obj):
    p = Path(p); p.parent.mkdir(parents=True, exist_ok=True)
    with p.open('x') as f:
        json.dump(obj, f, indent=2, allow_nan=False)


def public_pairs(rows):
    """Require identical event identity, kickoff, book, scan and mirrored line.
    Does not certify original sportsbook update time or jurisdiction.
    """
    groups = defaultdict(list); failures = Counter(); seen = set()
    for row in rows:
        try:
            if row['sport'] != 'americanfootball_ncaaf':
                raise ValueError('wrong_sport')
            if instant(row['snapshot_ts']) >= instant(row['commence_time']):
                raise ValueError('not_pregame')
            odds_profit(int(row['american_odds']))
            market = row['market']; side = row['side']
            if market not in ('ml', 'spread', 'total'):
                raise ValueError('unsupported_market')
            if side not in (('over','under') if market == 'total' else ('home','away')):
                raise ValueError('unsupported_side')
            line = None if market == 'ml' and not row['line'] else float(row['line'])
            if market == 'ml' and line is not None:
                raise ValueError('moneyline_threshold')
            if market != 'ml' and (not math.isfinite(line) or line*2 != round(line*2)
                                   or market == 'total' and line <= 0):
                raise ValueError('invalid_line')
            key = tuple(row[k] for k in ('game_id','home','away','commence_time','book','snapshot_ts','market'))
            canonical_line = -line if market == 'spread' and side == 'away' else line
            identity = key + (canonical_line, side, int(row['american_odds']))
            if identity in seen:
                failures['duplicate_row'] += 1; continue
            seen.add(identity); groups[key + (canonical_line,)].append(row)
        except (ValueError, KeyError, TypeError, OverflowError) as exc:
            failures[str(exc)] += 1
    pairs=[]
    for key, group in groups.items():
        primary = 'over' if key[-2] == 'total' else 'home'
        secondary = 'under' if primary == 'over' else 'away'
        left=[r for r in group if r['side']==primary]; right=[r for r in group if r['side']==secondary]
        if len(left)!=1 or len(right)!=1:
            failures['missing_or_ambiguous_opposing_pair'] += len(group); continue
        a,b=left[0],right[0]
        p=implied(int(a['american_odds'])); q=implied(int(b['american_odds']))
        pairs.append(dict(a, opposing_american_odds=int(b['american_odds']),
                          independently_recomputed_proportional_novig=p/(p+q),
                          provider_original_update_authenticated=False))
    return pairs,dict(failures)


def cluster_ci(rows, seed=20261109):
    if not rows: return None
    groups=defaultdict(list)
    for r in rows:groups[r['event_id']].append(r)
    stats=[]
    for rs in groups.values():
        usable=[r for r in rs if r['outcome']]; selected=[r for r in rs if r['hypothetical_selected']]
        stats.append([len(usable),sum((r['model_conditional_win']-(r['outcome']==1))**2 for r in usable),
                      sum((r['no_vig_conditional_win']-(r['outcome']==1))**2 for r in usable),
                      len(selected),sum(r['hypothetical_profit_per_1_risk'] for r in selected)])
    a=np.array(stats); rng=np.random.default_rng(seed); delta=[]; roi=[]
    for _ in range(1000):
        s=a[rng.integers(0,len(a),len(a))].sum(axis=0)
        if s[0]:delta.append((s[1]-s[2])/s[0])
        if s[3]:roi.append(s[4]/s[3])
    ci=lambda v:np.quantile(v,[.025,.975]).tolist() if v else None
    return dict(paired_brier_delta_95pct=ci(delta),roi_95pct=ci(roi),event_clusters=len(a),
                replicates=1000,seed=seed,interpretation='descriptive event clusters; not week/season independent confirmation')


def summarize(rows):
    result=metrics(rows); result['unique_events']=len({r['event_id'] for r in rows})
    pnl=defaultdict(float)
    for r in rows:pnl[(r['start_time_utc'],r['event_id'])]+=r['hypothetical_profit_per_1_risk']
    balance=peak=dd=0
    for key in sorted(pnl):
        balance+=pnl[key];peak=max(peak,balance);dd=max(dd,peak-balance)
    result['max_drawdown_units']=dd
    result['confidence_intervals']=cluster_ci(rows)
    return result


def inspect_public(odds, results):
    with Path(odds).open() as f:raw=list(csv.DictReader(f))
    pairs,failures=public_pairs(raw)
    identities=defaultdict(set)
    for r in raw:identities[r['game_id']].add((r['home'],r['away'],instant(r['commence_time']).isoformat()))
    revised={k for k,v in identities.items() if len(v)>1}
    with Path(results).open() as f:rr=list(csv.DictReader(f))
    lookup=defaultdict(list)
    for r in rr:
        if r['venue']=='home':lookup[(r['game_id'],r['team'],r['opponent'],instant(r['commence_time']))].append(r)
    # One last candidate scan per event/book/market/line, never synthetic best-book price.
    latest={}
    for q in pairs:
        key=(q['game_id'],q['book'],q['market'],q['line'])
        if key not in latest or instant(q['snapshot_ts'])>instant(latest[key]['snapshot_ts']):latest[key]=q
    counts=Counter();bookrows=Counter(r['book'] for r in raw); marketrows=Counter(r['market'] for r in raw)
    benchmark=defaultdict(list); unmatched=set(); matched=set()
    for q in latest.values():
        if q['game_id'] in revised:
            counts['identity_revision_quarantined_pairs']+=1;continue
        ident=(q['game_id'],q['home'],q['away'],instant(q['commence_time']))
        rs=lookup.get(ident,[])
        if len(rs)!=1:unmatched.add(q['game_id']);counts['unmatched_latest_pairs']+=1;continue
        r=rs[0];matched.add(q['game_id']);m={'ml':'moneyline','spread':'spread','total':'total'}[q['market']]
        score=dict(home_score=int(r['team_score']),away_score=int(r['opp_score']),market=m,
                   selection=q['side'],line='' if m=='moneyline' else float(q['line']))
        outcome=settlement(score)
        # Provider-score-only benchmark; no invented model p and no model-based bet selection.
        benchmark[(q['book'],m)].append((q['game_id'],outcome,q['independently_recomputed_proportional_novig'],int(q['american_odds'])))
    bm=[]
    for (book,m),rs in sorted(benchmark.items()):
        non=[r for r in rs if r[1]]
        bm.append(dict(book=book,market=m,paired_lines=len(rs),unique_games=len({r[0] for r in rs}),pushes=len(rs)-len(non),
                       conditional_novig_brier=sum((p-(o==1))**2 for _,o,p,_ in non)/len(non) if non else None,
                       model_brier=None,model_roi=None,model_coverage=0))
    return dict(cohort='EXPLORATORY_PUBLIC_SAMPLE_NOT_HOLDOUT',raw_rows=len(raw),games=len({r['game_id'] for r in raw}),
                books=dict(bookrows),markets=dict(marketrows),snapshot_range=[min(r['snapshot_ts'] for r in raw),max(r['snapshot_ts'] for r in raw)],
                kickoff_range=[min(r['commence_time'] for r in raw),max(r['commence_time'] for r in raw)],
                paired_primary_records=len(pairs),rejections=failures,latest_book_market_line_pairs=len(latest),
                result_rows=len(rr),matched_result_games=len(matched),unmatched_result_games=sorted(unmatched),
                result_join_rejections=dict(counts),benchmark_by_book_market=bm,raw_examples=raw[:4],
                identity_revision_events=sorted(revised),
                events_outside_advertised_ET_game_week=len({r['game_id'] for r in raw if not ('2026-10-19' <= instant(r['commence_time']).astimezone(__import__('zoneinfo').ZoneInfo('America/New_York')).date().isoformat() <= '2026-10-25')}),
                last_scan_age_minutes_quantiles=np.quantile([(instant(q['commence_time'])-instant(q['snapshot_ts'])).total_seconds()/60 for q in latest.values()],[0,.5,.95,1]).tolist(),
                original_quote_authentication=False,original_forecast_coverage=0,
                missing_model_reason='Sample precedes Nov 3 official release; no eligible immutable pregame model probabilities joined. Do not apply later-fit official model backward.',
                elo_spread_total=None,production_approved=False,approved_risk=0)


def replay(path, original_report, source_snapshot):
    old=json.loads(Path(original_report).read_text());assert digest(path)==old['joined_input_sha256']
    for year,h in old['fold_model_sha256'].items():assert digest(Path(path).parent/f'fold-model-{year}.json')==h
    assert digest(source_snapshot)==old['source_snapshot_sha256']
    from project_craps.common import unwrap
    from project_craps.features import historical_features
    games=unwrap(json.loads(Path(source_snapshot).read_text()))['games']
    features,_=historical_features([g for g in games if g['season']<=2025])
    elo={g['event_id']:1/(1+10**(-x[4]/400)) for g,x in features}
    grouped=defaultdict(list); bybook=defaultdict(list);errors=Counter();n=0
    for line in Path(path).open():
        n+=1;q=json.loads(line)
        try:r=checked(q)
        except (ValueError,KeyError,TypeError) as exc:errors[str(exc)]+=1;continue
        r['start_time_utc']=q['start_time_utc'];r['elo']=elo.get(q['event_id'])
        grouped[(r['season'],r['market'])].append(r);bybook[(r['season'],r['market'],r['book'])].append(r)
    seasons=[]
    for (year,m),rs in sorted(grouped.items()):
        z=dict(season=year,market=m,**summarize(rs))
        for prior in old['by_season_market']:
            if (prior['season'],prior['market'])==(year,m):
                for k in ('model_conditional_brier','same_quote_novig_conditional_brier','hypothetical_roi'):
                    assert abs(z[k]-prior[k])<1e-10
        z['elo_conditional_brier_paired_quotes']=sum(((r['elo'] if r['selection']=='home' else 1-r['elo'])-(r['outcome']==1))**2 for r in rs)/len(rs) if m=='moneyline' and all(r['elo'] is not None for r in rs) else None
        seasons.append(z)
    books=[dict(season=y,market=m,book=b,**summarize(rs)) for (y,m,b),rs in sorted(bybook.items())]
    return dict(cohort='ALREADY_EXAMINED_2022_2025_CHRONOLOGICAL_REPLAY',input_sha256=digest(path),read_rows=n,rejections=dict(errors),
                season_market=seasons,season_market_book=books,source_coverage=old['coverage'],
                model='Saved chronological architecture folds; not frozen Nov 3 official model applied backward',
                elo='Independent historical_features pregame Elo; winner only. Spread/total distribution unavailable.',
                original_quote_authentication=False,forecast_issuance='retrospective simulated cutoff, not contemporaneous issuance',
                portfolio='one unit per selected quote, correlated books/sides; drawdown ordered by kickoff, not settlement; diagnostic only',
                clv=None,paid_requests=0,production_approved=False)


def append_shadow(state, payload):
    """Locked hash-chain, exclusive per-record file; replay verifies before append."""
    state=Path(state);state.mkdir(parents=True,exist_ok=True,mode=0o700)
    with (state/'lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        chain=state/'journal.jsonl';prev='0'*64;count=0
        for line in chain.read_text().splitlines() if chain.exists() else []:
            r=json.loads(line);assert r['previous']==prev
            body=(state/r['file']).read_bytes();assert hashlib.sha256(body).hexdigest()==r['sha256']
            prev=hashlib.sha256(line.encode()).hexdigest();count+=1
        body=json.dumps(payload,sort_keys=True,allow_nan=False).encode();h=hashlib.sha256(body).hexdigest()
        name=f'{count+1:08d}-{h}.json'
        with (state/name).open('xb') as f:f.write(body)
        rec=dict(previous=prev,file=name,sha256=h)
        with chain.open('a') as f:f.write(json.dumps(rec,sort_keys=True)+'\n');f.flush();__import__('os').fsync(f.fileno())
        return dict(records=count+1,record_sha256=h,file=name)


def shadow_capture(state, status_path):
    import requests
    from .ncaaf_focus import reference_pairs
    from . import beta_daily
    from project_craps.model import outcome_masses
    registration=json.loads((Path(state)/'registration.json').read_text())
    for filename,h in registration['code_sha256'].items():
        if digest(Path(__file__).parent/filename)!=h:raise ValueError('shadow code registration drift: '+filename)
    pointer,runtime=beta_daily.official_check();model_file=Path(pointer['sports']['NCAAF']['path'])
    wrapped=json.loads(model_file.read_text());model=wrapped.get('payload',wrapped)
    status=json.loads(Path(status_path).read_text());now=datetime.now(timezone.utc)
    if (now-instant(status['asof'])).total_seconds()>3600:raise ValueError('stale calendar')
    payload=dict(observed_at=now.isoformat(),cohort='PROSPECTIVE_EXPLORATORY_SHADOW_NOT_CONFIRMATION',events=[],approved_risk=0)
    for event in status['events']:
        gid=event['event_id'];url=f'https://site.api.espn.com/apis/site/v2/sports/football/college-football/summary?event={gid}'
        try:
            response=requests.get(url,timeout=20);response.raise_for_status();data=response.json();received=datetime.now(timezone.utc)
            c=data['header']['competitions'][0];sides={t['homeAway']:t for t in c['competitors']}
            e=dict(home_id=str(sides['home']['team']['id']),away_id=str(sides['away']['team']['id']),kickoff=c['date'])
            if str(data['header']['id'])!=gid or instant(e['kickoff'])<=received or c['status']['type']['state']!='pre':raise ValueError('not exact unstarted event')
            quotes=reference_pairs(data,e)
            row=dict(event_id=gid,identity=e,received_at=received.isoformat(),url=url,source_sha256=hashlib.sha256(response.content).hexdigest(),raw_source=data,quotes=quotes,model_probabilities_status='unavailable')
            refs=list(Path(runtime['first_forecast_registry']).glob('NCAAF-'+gid+'-*.json'))
            if len(refs)==1:
                ref=json.loads(refs[0].read_text())
                if ref['record_sha256']!=beta_daily.reference_digest(ref):raise ValueError('forecast drift')
                if ref['model_sha256']!=pointer['sports']['NCAAF']['sha256'] or any(ref[k]!=e[k] for k in ('home_id','away_id')) or instant(ref['kickoff'])!=instant(e['kickoff']):raise ValueError('forecast identity/model revision')
                if instant(ref['issued_at'])>=received:raise ValueError('invalid forecast time')
                scores=beta_daily.reference_scores(ref,model)
                for q in quotes:q['derived_point_kernel_WPL']=list(outcome_masses(scores,q['market'],q['selection'],q['line'],tie_policy='refund' if q['market']=='moneyline' else None))
                row.update(model_probabilities_status='new derived point-kernel shadow; old feature cutoff retained; not original market forecast',parent_record_sha256=ref['record_sha256'],feature_cutoff=ref['feature_cutoff'])
            row['decision']='PASS: source quote time, settlement scope, QB/roster/workload/weather and executable legal-book evidence incomplete'
            payload['events'].append(row)
        except Exception as exc:payload['events'].append(dict(event_id=gid,error=type(exc).__name__+': '+str(exc),approved_risk=0))
    receipt=append_shadow(state,payload)
    return dict(**receipt,event_count=len(payload['events']),quote_pairs=sum(len(e.get('quotes',[])) for e in payload['events']),failures=sum('error' in e for e in payload['events']),approved_risk=0)


def main():
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='cmd',required=True)
    a=sub.add_parser('public');a.add_argument('--odds',required=True);a.add_argument('--results',required=True);a.add_argument('--output',required=True)
    a=sub.add_parser('replay');a.add_argument('--input',required=True);a.add_argument('--original-report',required=True);a.add_argument('--source-snapshot',required=True);a.add_argument('--output',required=True)
    a=sub.add_parser('shadow');a.add_argument('--state',required=True);a.add_argument('--calendar',required=True);a.add_argument('--output',required=True)
    a=p.parse_args()
    if a.cmd=='public':r=inspect_public(a.odds,a.results)
    elif a.cmd=='replay':r=replay(a.input,a.original_report,a.source_snapshot)
    else:r=shadow_capture(a.state,a.calendar)
    write_new(a.output,r);print(json.dumps({k:v for k,v in r.items() if k in ('raw_rows','games','paired_primary_records','read_rows','rejections','event_count','quote_pairs','failures')}))
if __name__=='__main__':main()
