"""Research-only distribution diagnostics; never a production model adapter.

Training residual pairs must be supplied before the evaluation cutoff. Joint
centering transfers their mean into the point prediction exactly once. No key
number lattice weights are inferred here. Quote authentication is external.
"""
import math
import random
from collections import defaultdict
from datetime import datetime


def _number(x):
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
        raise ValueError('finite numeric value required')
    return float(x)


def _time(s):
    d = datetime.fromisoformat(s.replace('Z', '+00:00'))
    if d.tzinfo is None:
        raise ValueError('aware time required')
    return d


def jointly_center(point, residual_pairs, *, fitted_through, forecast_cutoff,
                   bias_already_applied=False):
    """Return equivalent continuous support with residual means zero.

    Refuses a stacked correction. All residuals must come from the declared
    training/calibration vintage; timestamp comparison does not authenticate it.
    """
    if bias_already_applied:
        raise ValueError('cannot stack residual-center correction on prior bias')
    if _time(fitted_through) >= _time(forecast_cutoff):
        raise ValueError('residual vintage must precede forecast')
    point = tuple(map(_number, point))
    pairs = [tuple(map(_number, p)) for p in residual_pairs]
    if len(point) != 2 or not pairs or any(len(p) != 2 for p in pairs):
        raise ValueError('paired margin,total support required')
    centers = tuple(sum(p[j] for p in pairs)/len(pairs) for j in range(2))
    return {'point': tuple(point[j]+centers[j] for j in range(2)),
            'residual_pairs': [tuple(p[j]-centers[j] for j in range(2)) for p in pairs],
            'transferred_center': centers, 'approval': 'RESEARCH_ONLY'}


def center_audit(point, residual_pairs, discrete_scores=None):
    p = tuple(map(_number, point)); pairs = list(residual_pairs)
    if len(p) != 2 or not pairs or any(len(r) != 2 for r in pairs):
        raise ValueError('paired support required')
    shift = [sum(_number(r[j]) for r in pairs)/len(pairs) for j in range(2)]
    result = {'point_margin_total': p, 'residual_mean_margin_total': shift,
              'continuous_distribution_mean': [p[j]+shift[j] for j in range(2)]}
    if discrete_scores is not None:
        s = list(discrete_scores)
        if not s or any(len(r) != 2 or any(_number(x)<0 or x!=int(x) for x in r) for r in s):
            raise ValueError('nonnegative integer score pairs required')
        means = [sum(h-a for h,a in s)/len(s), sum(h+a for h,a in s)/len(s)]
        result.update(discrete_distribution_mean=means,
                      discretization_shift=[means[j]-p[j]-shift[j] for j in range(2)])
    return result


def proper_scores(masses, outcome):
    p = tuple(map(_number, masses))
    if len(p)!=3 or any(x<0 or x>1 for x in p) or not math.isclose(sum(p),1,abs_tol=1e-10):
        raise ValueError('normalized W/P/L masses required')
    if outcome not in (1,0,-1):
        raise ValueError('outcome must be win1,push0,loss-1')
    i = {1:0,0:1,-1:2}[outcome]
    q = p[0]/(1-p[1]) if p[1]<1 else None
    return {'threeway_brier':sum((x-(j==i))**2 for j,x in enumerate(p)),
            'threeway_logloss':-math.log(p[i]) if p[i]>0 else float('inf'),
            'conditional_win':q,
            'conditional_brier':(q-(outcome==1))**2 if outcome!=0 and q is not None else None,
            'conditional_logloss':(-math.log(q if outcome==1 else 1-q)
              if 0<q<1 else (0. if q==float(outcome==1) else float('inf')))
              if outcome!=0 and q is not None else None}


def _profit(american):
    x=_number(american)
    if x!=int(x) or abs(x)<100:
        raise ValueError('invalid American odds')
    return x/100 if x>0 else 100/-x


def same_book_novig(a,b):
    """Both offers explicit; complementary sides, event, scope, line and time."""
    for k in ('event_id','book','market','scope','quote_time_utc'):
        if not a.get(k) or a[k]!=b.get(k):
            raise ValueError('same-book pair mismatch: '+k)
    sides={'moneyline':{'home','away'},'spread':{'home','away'},'total':{'over','under'}}
    market=a['market']
    if market not in sides or {a['selection'],b['selection']}!=sides[market]:
        raise ValueError('opposing sides required')
    if a['scope']!='full_game_including_overtime':
        raise ValueError('unsupported scope')
    for row in (a,b):
        if _time(row['quote_time_utc']) >= _time(row['start_time_utc']):
            raise ValueError('post-start quote')
    if a['start_time_utc']!=b['start_time_utc']:
        raise ValueError('different kickoff')
    if market=='moneyline':
        if a.get('line') is not None or b.get('line') is not None:
            raise ValueError('moneyline line must be null')
    else:
        x,y=_number(a['line']),_number(b['line'])
        if x*2!=int(x*2) or y*2!=int(y*2) or (market=='total' and x<=0):
            raise ValueError('integer/half line required')
        if not math.isclose(x,-y if market=='spread' else y,abs_tol=1e-10):
            raise ValueError('different line')
    x=1/(1+_profit(a['american_odds']));y=1/(1+_profit(b['american_odds']))
    return x/(x+y)


def expected_roi(masses,american):
    proper_scores(masses,1)
    return masses[0]*_profit(american)-masses[2]


def event_balanced(rows, field):
    """Within-event row average, then equal event weight; nulls excluded explicitly."""
    g=defaultdict(list)
    for r in rows:
        if r.get(field) is not None:
            g[str(r['event_id'])].append(_number(r[field]))
    means=[sum(v)/len(v) for v in g.values()]
    return {'value':sum(means)/len(means) if means else None,'events':len(means),
            'usable_rows':sum(map(len,g.values())), 'weighting':'equal event after within-event mean'}


def week_block_ci(rows, field, *, replicates=1000, seed=20261105):
    """Paired differences may be passed as field. Fewer8 blocks => no interval."""
    blocks=defaultdict(list); event_block={}
    for r in rows:
        key=(r['season'],r['week']);event=str(r['event_id'])
        if event in event_block and event_block[event]!=key:
            raise ValueError('event assigned to multiple week blocks')
        event_block[event]=key;blocks[key].append(r)
    valid=[b for b in blocks.values() if event_balanced(b,field)['events']]
    base=event_balanced(rows,field)
    if len(valid)<8:
        return dict(base,blocks=len(valid),interval=None,reason='fewer than8 week blocks')
    if replicates<100:
        raise ValueError('at least100 bootstrap replicates')
    rng=random.Random(seed);vals=[]
    block_stats=[event_balanced(b,field) for b in valid]
    for _ in range(replicates):
        # Aggregate sufficient per-block event sums; repeated blocks must retain multiplicity.
        stats=[rng.choice(block_stats) for j in valid]
        vals.append(sum(s['value']*s['events'] for s in stats)/sum(s['events'] for s in stats))
    vals.sort()
    return dict(base,blocks=len(valid),interval=[vals[int(.025*(replicates-1))],vals[int(.975*(replicates-1))]],
                replicates=replicates,unit='season-week; descriptive, not cross-season independence')


def offered_line_push_diagnostic(rows):
    """Only supplied offered lines; averages quotes within event/market/line first."""
    groups=defaultdict(list)
    for r in rows:
        market=r['market'];line=r.get('line')
        if market not in ('spread','total'):
            continue
        x=_number(line)
        if x*2!=int(x*2) or market=='total' and x<=0:
            raise ValueError('invalid offered line')
        proper_scores((r['p_win'],r['p_push'],r['p_loss']),r['outcome'])
        if x!=int(x) and (r['p_push']!=0 or r['outcome']==0):
            raise ValueError('half-line push impossible')
        # Mirror spread sides into the home handicap, preserving asymmetric margins.
        canonical=-x if market=='spread' and r['selection']=='away' else x
        groups[(market,canonical)].append(dict(r,push_actual=float(r['outcome']==0)))
    return [{'market':m,'home_handicap_or_total':line,
             'predicted_push':event_balanced(rs,'p_push'),
             'observed_push':event_balanced(rs,'push_actual')}
            for (m,line),rs in sorted(groups.items())]


def fixed_policy_roi(tickets, *, policy_frozen_at):
    """Audit an externally frozen one-ticket/event-market policy; never select here."""
    seen=set();profit=risk=0.
    for t in tickets:
        key=(str(t['event_id']),t['market'])
        if key in seen:raise ValueError('duplicate event-market ticket')
        seen.add(key)
        if _time(policy_frozen_at)>_time(t['decision_time_utc']):raise ValueError('policy frozen after decision')
        if _time(t['decision_time_utc'])>=_time(t['start_time_utc']):raise ValueError('post-start decision')
        if not t.get('source_authenticated'):raise ValueError('source authentication required for fixed-policy claim')
        stake=_number(t['stake'])
        if stake<=0 or t['outcome'] not in (1,0,-1):raise ValueError('invalid ticket')
        risk+=stake;profit+=stake*(_profit(t['american_odds']) if t['outcome']==1 else -1 if t['outcome']==-1 else 0)
    return {'tickets':len(seen),'units_risked':risk,'profit':profit,'roi':profit/risk if risk else None,
            'approval':'RESEARCH_ONLY','interval':None,'interval_reason':'requires predeclared dependent-ticket block design'}


def calibrate_joint_support(scores, calibration_results, *, key_margins,
                            smoothing, fitted_through, forecast_cutoff):
    """Calibration-only shared joint-score reweighting; never add support atoms.

    Caller must prespecify signed key margins and positive pseudocount.
    Shrinks empirical category rates toward original support rates. Original
    publication/source authentication remains an external requirement.
    """
    s=[tuple(pair) for pair in scores]
    center_audit((0,0),[(0,0)],s)
    alpha=_number(smoothing)
    if alpha<=0:raise ValueError('positive explicit smoothing required')
    keys=set(key_margins)
    if not keys or any(isinstance(x,bool) or not isinstance(x,int) for x in keys):
        raise ValueError('explicit signed integer key margins required')
    fit=_time(fitted_through)
    if fit>=_time(forecast_cutoff):raise ValueError('calibration overlaps forecast')
    category=lambda margin:margin if margin in keys else 'other'
    support=defaultdict(int)
    for h,a in s:support[category(h-a)]+=1
    empirical=defaultdict(int);seen=set()
    for r in calibration_results:
        if str(r['event_id']) in seen:raise ValueError('duplicate calibration game')
        seen.add(str(r['event_id']))
        if _time(r['observed_at'])>fit or _time(r['kickoff'])>=_time(r['observed_at']):
            raise ValueError('result not available by calibration cutoff')
        h,a=r['home_score'],r['away_score']
        if any(_number(x)<0 or x!=int(x) for x in (h,a)):raise ValueError('integer scores required')
        empirical[category(h-a)]+=1
    if not seen:raise ValueError('calibration games required')
    unsupported=[k for k,n in empirical.items() if n and not support[k]]
    if unsupported:raise ValueError('observed category absent from support: '+str(unsupported))
    n=len(s);m=len(seen)
    target={k:(empirical[k]+alpha*(count/n))/(m+alpha) for k,count in support.items() if count}
    weights=[target[category(h-a)]/support[category(h-a)] for h,a in s]
    return {'scores':s,'weights':weights,'category_probabilities':target,
            'calibration_events':m,'key_margins':sorted(keys),'smoothing':alpha,
            'fitted_through':fitted_through,'approval':'RESEARCH_ONLY',
            'method':'shared joint-score reweighting; no support atoms added'}


def weighted_outcome_masses(candidate, market, selection, line=None):
    """All markets use the identical weighted integer joint score candidate."""
    scores=candidate['scores'];weights=candidate['weights']
    if len(scores)!=len(weights) or not scores or any(_number(w)<0 for w in weights) or not math.isclose(sum(weights),1,abs_tol=1e-10):
        raise ValueError('normalized weighted score support required')
    center_audit((0,0),[(0,0)],scores)
    if market not in ('moneyline','spread','total'):raise ValueError('unsupported market')
    if selection not in ({'over','under'} if market=='total' else {'home','away'}):raise ValueError('invalid selection')
    if market=='moneyline':
        if line is not None:raise ValueError('moneyline line must be null')
    else:
        line=_number(line)
        if line*2!=int(line*2) or market=='total' and line<=0:raise ValueError('invalid line')
    values=[0.,0.,0.]
    for (h,a),w in zip(scores,weights):
        x=(h+a-line)*(1 if selection=='over' else -1) if market=='total' else (h-a)*(1 if selection=='home' else -1)+(line if market=='spread' else 0)
        values[0 if x>0 else 1 if x==0 else 2]+=w
    return tuple(values)
