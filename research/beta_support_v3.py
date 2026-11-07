"""Separate NCAAB support challenger. No fitting, official writes or promotion.

The geometric contamination component is a fixed structural experiment, not an
estimated advantage. It is deliberately broad. Its weight has not been tuned on
the inspected pilot. All markets project the same joint distribution.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
import hashlib
import json
import math
from pathlib import Path

VERSION = 'ncaab-support-v3-20261107'
POLICY = dict(version=VERSION, approval='RESEARCH_ONLY', sport='NCAAB',
    minimum_prior_games=5, require_same_training_component=True,
    tail_weight=0.01, tail_family='independent zero-based geometric scores conditioned on unequal scores',
    tail_mean_floor=1., tail_mean_ceiling=250., maximum_absolute_line=500.,
    design_basis='Structural choice, not fitted/tuned or accuracy validated; broad tail may worsen scores',
    confirmation='CLOSED; all earlier examined events excluded; future power/cluster design required',
    injury='UNAVAILABLE without identified values and verified allocations',
    promotion=False, real_risk=0)

def canonical(x):
    return json.dumps(x, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def instant(s):
    t = datetime.fromisoformat(s.replace('Z', '+00:00'))
    if t.tzinfo is None:
        raise ValueError('timezone required')
    return t

def training_support(rows, home, away, cutoff):
    """Only timestamp-eligible rows; no outcome- or opponent-name exclusions."""
    graph = defaultdict(set); counts = Counter(); seen = set()
    for r in rows:
        if r['event_id'] in seen:
            raise ValueError('duplicate training game')
        seen.add(r['event_id'])
        if not instant(r['kickoff']) < instant(r['result_observed_at']) < instant(cutoff):
            raise ValueError('training availability must precede cutoff')
        h, a = str(r['home_id']), str(r['away_id'])
        if h == a:
            raise ValueError('same participant')
        graph[h].add(a); graph[a].add(h); counts[h] += 1; counts[a] += 1
    visited = set(); stack = [str(home)] if str(home) in graph else []
    while stack:
        t = stack.pop()
        if t in visited: continue
        visited.add(t); stack.extend(graph[t] - visited)
    reasons = []
    if min(counts[str(home)], counts[str(away)]) < POLICY['minimum_prior_games']:
        reasons.append('insufficient_prior_team_games')
    if str(away) not in visited:
        reasons.append('disconnected_training_components')
    return dict(supported=not reasons, reasons=reasons,
                home_games=counts[str(home)], away_games=counts[str(away)],
                component_size=len(visited), evidence_scope='captured history; publication time not independently authenticated')

def _line(market, side, line):
    allowed = {'moneyline': ('home', 'away'), 'spread': ('home', 'away'), 'total': ('over', 'under')}
    if market not in allowed or side not in allowed[market]:
        raise ValueError('unsupported market/side')
    if market == 'moneyline':
        if line is not None: raise ValueError('moneyline must not have line')
        return 0.
    if isinstance(line, bool) or not isinstance(line, (int, float)) or not math.isfinite(line):
        raise ValueError('finite line required')
    if abs(line) > POLICY['maximum_absolute_line'] or abs(line*2-round(line*2)) > 1e-10:
        raise ValueError('line outside declared integer/half-point scope')
    if market == 'total' and line < .5:
        raise ValueError('positive total required')
    return float(line)

def geometric_masses(home_mean, away_mean, market, side, line=None):
    """Analytic unbounded joint-score tail, never independent market smoothing.

    H,A are independent geometric counts before conditioning H!=A. Integer-score
    support makes moneyline ties impossible and integer spread/total pushes real.
    Direct survival sums avoid subtracting tiny tails from one.
    """
    line = _line(market, side, line)
    means = [home_mean, away_mean]
    if any(not math.isfinite(v) or not POLICY['tail_mean_floor'] <= v <= POLICY['tail_mean_ceiling'] for v in means):
        raise ValueError('tail score mean outside declared scope')
    qh, qa = [v/(v+1) for v in means]
    base = (1-qh)*(1-qa); product = qh*qa
    tie = base/(1-product); norm = 1-tie
    def diff_pmf(d): return tie*(qh**d if d >= 0 else qa**(-d))
    def ge(k, h=qh, a=qa):
        if k >= 1: return tie*h**k/(1-h)
        return 1-tie*a**(1-k)/(1-a)
    def total_pmf(n):
        if n < 0: return 0.
        return base*math.fsum(qh**h*qa**(n-h) for h in range(n+1) if h*2 != n)
    def total_above(n):
        if n < 0: return norm
        all_above = qh**(n+1) + (1-qh)*math.fsum(qh**h*qa**(n-h+1) for h in range(n+1))
        tied_above = tie*product**(n//2+1)
        return all_above-tied_above
    if market in ('moneyline', 'spread'):
        # Side-line convention: away+3 is A-H+3; invert onto D=H-A.
        threshold = -line if side == 'home' else line
        above = ge(math.floor(threshold)+1)
        below = ge(1-math.ceil(threshold), qa, qh)
        if threshold < 0: above -= tie
        if threshold > 0: below -= tie
        push = diff_pmf(int(threshold)) if threshold.is_integer() and threshold != 0 else 0.
        win, loss = (above, below) if side == 'home' else (below, above)
    else:
        nlo = math.ceil(line)-1
        below = math.fsum(total_pmf(n) for n in range(nlo+1))
        above = total_above(math.floor(line))
        push = total_pmf(int(line)) if line.is_integer() else 0.
        win, loss = (above, below) if side == 'over' else (below, above)
    p = [win/norm, push/norm, loss/norm]
    if min(p) < 0 or not math.isclose(sum(p), 1., abs_tol=1e-10):
        raise ValueError('joint tail numerical failure')
    return [v/sum(p) for v in p]

def project(candidate, market, side, line=None):
    from research.probability_v2 import weighted_outcome_masses
    _line(market, side, line)
    scores, weights = candidate['scores'], candidate['weights']
    if any(h == a for h, a in scores): raise ValueError('NCAAB ties prohibited')
    raw = weighted_outcome_masses(candidate, market, side, line)
    means = [max(POLICY['tail_mean_floor'], math.fsum(s[i]*w for s,w in zip(scores,weights))) for i in [0,1]]
    tail = geometric_masses(*means, market, side, line)
    w = POLICY['tail_weight']
    return [(1-w)*a+w*b for a,b in zip(raw,tail)]

def correction_view(original, current, evidence):
    """A derived view never clears identity/time quarantine or rewrites a grade."""
    keys = ['home_id', 'away_id', 'kickoff']
    changes = [k for k in keys if original['identity'][k] != current[k]]
    if changes: return dict(status='QUARANTINED', reasons=changes, eligible_for_approval=False)
    required = {'independent_source', 'captured_at', 'sha256', 'home_score', 'away_score'}
    if not required <= evidence.keys() or not evidence['independent_source']:
        return dict(status='QUARANTINED', reasons=['independent_correction_evidence_missing'], eligible_for_approval=False)
    if [evidence['home_score'], evidence['away_score']] != [current['home_score'], current['away_score']]:
        return dict(status='QUARANTINED', reasons=['sources_disagree'], eligible_for_approval=False)
    return dict(status='CORROBORATED_DESCRIPTIVE_VIEW', result=current,
                evidence=evidence, original_preserved=True, eligible_for_approval=False)

def confirmation_allowed(event_id, registration, power_plan=None):
    # Software readiness cannot become statistical approval by passing a game count.
    return dict(allowed=False, reason='examined_or_pilot_event' if event_id in registration['excluded_events']
                else 'separate_preregistered_power_and_confirmation_protocol_required')

def create(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    value = dict(value)
    value['record_sha256'] = hashlib.sha256(canonical(value)).hexdigest()
    with path.open('xb') as f: f.write(canonical(value))
    path.chmod(0o600)

def verified_read(path):
    value = json.loads(Path(path).read_text()); expected = value.pop('record_sha256')
    if hashlib.sha256(canonical(value)).hexdigest() != expected:
        raise ValueError('v3 record drift: '+str(path))
    return value

def verify(state):
    from research.beta_v2.daily_entry import check_entry
    from research.beta_v2.runtime import load_bundle, STATE
    check_entry(); load_bundle(STATE)
    registration = verified_read(state/'registration.json')
    if registration['policy'] != POLICY: raise ValueError('v3 policy drift')
    for path, digest in registration['files'].items():
        if sha(path) != digest: raise ValueError('v3 registered code drift: '+path)
    for directory in ['forecasts','settlements','quarantines']:
        for path in (state/directory).glob('*.json'): verified_read(path)
    return registration

def register(state):
    from research.beta_v2.daily_entry import check_entry
    from research.beta_v2.runtime import STATE, load_bundle
    from research.beta_daily import integrity
    check_entry(); load_bundle(STATE)
    if (state/'registration.json').exists(): return verify(state)
    files = [Path(__file__).resolve(), Path(__file__).with_name('beta_v2')/'protocol.py']
    # Register outcome-inspected and existing forecast events before prospective use.
    excluded = sorted({integrity(p)['event_id'] for p in (STATE/'forecasts').glob('*.json')})
    value = dict(policy=POLICY, registered_at=datetime.now(timezone.utc).isoformat(),
                 files={str(p):sha(p) for p in files}, excluded_events=excluded,
                 baseline_source='all existing v2 event IDs, including unstarted registered games; conservative exclusion',
                 confirmation_open=False, development_status='FIU failure inspected; structural repair evidence only',
                 pilot_policy='All new v3 records remain pilot; no confirmation until a separate fixed design is authorized')
    create(state/'registration.json', value)
    return value

def grade_record(record, event, registration):
    """Exact identity, kickoff and neutral-site grading. No score correction in place."""
    from research.beta_v2.runtime import outcome
    from research.beta_v2.calibration import proper_scores
    if event['status'] != 'FINAL': return None
    if record['event_id'] != event['event_id']:
        raise ValueError('result event identity revision')
    for k in ['home_id','away_id','neutral']:
        if record['identity'][k] != event[k]: raise ValueError('result identity revision: '+k)
    if instant(record['identity']['kickoff']) != instant(event['kickoff']):
        raise ValueError('result kickoff revision')
    if not instant(registration['registered_at']) <= instant(record['issued_at']) < instant(event['kickoff']) < instant(event['observed_at']):
        raise ValueError('invalid prospective clocks')
    grades={}
    for name, masses in [('support_v3',record['masses']),('paired_parent',record['paired_fresh_parent_masses'])]:
        if masses: grades[name]={k:proper_scores(p,outcome(k,event)) for k,p in masses.items()}
    return dict(event_id=record['event_id'],horizon=record['horizon'],issued_at=record['issued_at'],
                identity=record['identity'],home_score=event['home_score'],away_score=event['away_score'],
                observed_at=event['observed_at'],grades=grades,support=record['support'],
                confirmation=record['confirmation'],real_risk=0)

def run(state, output):
    import requests
    from research.beta_v2.runtime import STATE, load_bundle, score_at
    from research.beta_v2.strength import predict
    from research.beta_v2.calibration import apply
    from research.beta_v2.protocol import horizon
    from research.beta_daily import parse_events, integrity
    from research.beta_v2 import benchmarks
    reg = verify(state); bundle, binding, models = load_bundle(STATE)
    model, cal = models['NCAAB']; rows = json.loads((bundle/'data/NCAAB-normalized.json').read_text())
    now = datetime.now(timezone.utc); stamp = now.strftime('%Y%m%dT%H%M%S%fZ')
    events=[]; receipts=[]; completed={}
    prior={p.name:verified_read(p) for p in (state/'forecasts').glob('*.json')}
    dates={(now+timedelta(days=day)).strftime('%Y%m%d') for day in [0,1,2]}
    dates.update(instant(r['identity']['kickoff']).strftime('%Y%m%d') for r in prior.values())
    # Free calendar only; no odds endpoint. Capture current exact event identity.
    for date in sorted(dates):
        r=requests.get('https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard',
                       params={'dates':date,'groups':50,'limit':1000},timeout=25)
        r.raise_for_status(); raw=state/'sources'/stamp/(date+'.json')
        raw.parent.mkdir(parents=True,exist_ok=True);raw.write_bytes(r.content);raw.chmod(0o600)
        observed=datetime.now(timezone.utc).isoformat()
        receipts.append(dict(url=r.url,observed_at=observed,sha256=sha(raw),publication_authenticated=False))
        es=parse_events(r.json(),'NCAAB',observed)
        completed.update({e['espn_event_id']:dict(e,event_id=e['espn_event_id']) for e in es if e['status']=='FINAL'})
        events += [dict(e,event_id=e['espn_event_id']) for e in es if e['status'] not in ['FINAL','INVALID_FINAL_TIE'] and horizon(e['kickoff'],observed)]
    refs=benchmarks.ncaab(events,datetime.now(timezone.utc).isoformat(),bundle/'data/current-ncaab')
    qpath=output.parent/'beta-model-lab/latest-v2-status.json'
    quarantined={q['event_id'] for q in json.loads(qpath.read_text()).get('quarantines',[])} if qpath.exists() else set()
    new=Counter(); blocked=Counter(); count=0
    for e in events:
        issued=datetime.now(timezone.utc).isoformat(); window=horizon(e['kickoff'],issued)
        if not window: continue
        path=state/'forecasts'/(e['event_id']+'-'+window+'.json')
        if path.exists(): continue
        support=training_support(rows,e['home_id'],e['away_id'],model['cutoff'])
        if not isinstance(e['neutral'],bool):
            support['supported']=False;support['reasons'].append('neutral_site_unverified')
        if e['event_id'] in quarantined:
            support['supported']=False;support['reasons'].append('existing_identity_or_score_quarantine')
        ref=refs.get(e['event_id'],{}); masses=None; parent_masses=None
        if support['supported']:
            p=predict(model,e); ps=p['point_scores']
            c=apply(p['paired_score_samples'],cal,dict(predicted_margin=ps[0]-ps[1],predicted_total=sum(ps),parent=cal['parent']))
            margin=sum((h-a)*w for (h,a),w in zip(c['scores'],c['weights']));total=sum((h+a)*w for (h,a),w in zip(c['scores'],c['weights']))
            lines=[('moneyline','home',None),('spread','home',-round(margin*2)/2),('total','over',max(.5,round(total*2)/2))]
            parent_masses=score_at(c,lines)
            masses={f'{m}:{s}:{l}':project(c,m,s,l) for m,s,l in lines}
        else:
            blocked.update(support['reasons'])
        record=dict(version=VERSION,sport='NCAAB',event_id=e['event_id'],horizon=window,issued_at=issued,
            identity={k:e[k] for k in ['home_id','away_id','home','away','kickoff','neutral']},
            bundle=binding,support=support,masses=masses,paired_fresh_parent_masses=parent_masses,
            official_winner_comparator=ref.get('official_winner_probability'),independent_elo=ref.get('independent_elo'),
            sources=receipts,feature_cutoff=model['cutoff'],source_authentication_verified=False,
            incomplete_inputs=['current player eligibility','verified replacement workload','identified injury values','authenticated book prices'],
            confirmation=confirmation_allowed(e['event_id'],reg),approval='RESEARCH_ONLY',real_risk=0)
        # Window recheck and exact source identity precede every immutable write.
        if horizon(e['kickoff'],issued)!=window: raise ValueError('window changed')
        create(path,record);new[window]+=1;count+=bool(masses)
    settled=0; revisions=[]
    for name,record in prior.items():
        event=completed.get(record['event_id'])
        if not event: continue
        target=state/'settlements'/name
        try:
            result=grade_record(record,event,reg)
            if target.exists():
                old=verified_read(target)
                if [old['home_score'],old['away_score']] != [event['home_score'],event['away_score']]:
                    raise ValueError('result score revision')
            elif result:
                create(target,result); settled+=1
        except ValueError as error:
            revisions.append(dict(event_id=record['event_id'],reason=str(error)))
            create(state/'quarantines'/(stamp+'-'+name),dict(event_id=record['event_id'],reason=str(error)))
    verify(state)
    status=dict(asof=datetime.now(timezone.utc).isoformat(),version=VERSION,new_records=dict(new),new_supported=count,
                new_settlements=settled,revisions=revisions,
                blocked_reasons=dict(blocked),confirmation_open=False,paid_requests=0,real_risk=0,
                note='New prospective pilot only. Missing inputs remain missing; no historical backfilled probabilities.')
    create(state/'runs'/(stamp+'.json'),status);output.mkdir(parents=True,exist_ok=True)
    (output/'V3_STATUS.json').write_text(json.dumps(status,indent=2)+'\n')
    return status

def main():
    import fcntl
    p=argparse.ArgumentParser();p.add_argument('--state',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--register',action='store_true');a=p.parse_args()
    a.state.mkdir(parents=True,exist_ok=True)
    with (a.state/'run.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if a.register: register(a.state)
        print(json.dumps(run(a.state,a.output),indent=2))

if __name__=='__main__': main()
