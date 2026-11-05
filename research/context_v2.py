"""Measured context helpers, with no fitted coefficients or production approval."""
import math
from statistics import mean
from project_craps.common import instant

VERSION = 'context-v2-research'
ABLATION_PROTOCOL = {
    'version': VERSION, 'approval': 'RESEARCH_ONLY',
    'selection': 'train-only chronological folds; existing inspected games exploratory',
    'arms': ['baseline', 'rest', 'travel', 'momentum_innovation', 'regulation_efficiency'],
    'confirmation': 'freeze one selected arm before untouched prospective evaluation',
    'scoring': 'event-balanced proper probability scores; push-aware settlement separate',
    'coefficients': 'NOT_FITTED',
}


def finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('finite number required')
    return float(value)


def observed(row, cutoff):
    """Capture timing is necessary, not independent source authentication."""
    if instant(row['observed_at']) > cutoff:
        raise ValueError('input observed after cutoff')
    if row.get('published_at') and instant(row['published_at']) > instant(row['observed_at']):
        raise ValueError('publication after observation')


def context(event, history, asof, *, travel=None):
    cutoff = instant(asof)
    if cutoff >= instant(event['kickoff']):
        raise ValueError('forecast cutoff must precede kickoff')
    output = {'version': VERSION, 'event_id': event['event_id'], 'approval': 'RESEARCH_ONLY', 'teams': {}}
    seen = set()
    eligible = []
    for game in history:
        if game['event_id'] in seen:
            raise ValueError('duplicate history event')
        seen.add(game['event_id'])
        if game['event_id'] == event['event_id']:
            raise ValueError('target in history')
        if game.get('status') != 'FINAL':
            continue
        observed(game, cutoff)
        if not instant(game['kickoff']) < instant(game['completed_at']) <= instant(game['observed_at']):
            raise ValueError('invalid final timing')
        eligible.append(game)
    for team in (event['home_id'], event['away_id']):
        games = sorted((g for g in eligible if team in (g['home_id'], g['away_id'])), key=lambda g: instant(g['kickoff']))
        last = games[-1] if games else None
        issues = []
        rest = (instant(event['kickoff']) - instant(last['completed_at'])).total_seconds() / 86400 if last else None
        if rest is None:
            issues.append('prior completion missing')
        residuals = []
        for g in [g for g in games if g['season'] == event['season']][-6:]:
            f = g.get('pregame_expectation')
            if not f:
                residuals.append(None)
                continue
            observed(f, instant(g['kickoff']))
            if not instant(f['observed_at']) < instant(g['kickoff']):
                raise ValueError('expectation not strictly pregame')
            if f.get('market_blind') is not True or instant(f['trained_through']) > instant(f['observed_at']):
                raise ValueError('invalid independent expectation')
            sign = 1 if g['home_id'] == team else -1
            residuals.append(sign * (finite(g['home_score']) - finite(g['away_score']) - finite(f['expected_home_margin'])))
        innovation = mean(residuals[-3:]) - mean(residuals[:3]) if len(residuals) == 6 and None not in residuals else None
        if innovation is None:
            issues.append('six complete independent pregame expectations unavailable')
        distance = None
        if travel and team in travel:
            t = travel[team]
            observed(t, cutoff)
            distance = great_circle_km(t['origin'], t['destination'])
            issues.append('geographic distance proxy; actual itinerary unverified')
        else:
            issues.append('travel origin/destination unavailable')
        output['teams'][team] = {'recovery_days': rest, 'travel_km_proxy': distance, 'momentum_innovation': innovation, 'missing_or_limitations': issues}
    return output


def great_circle_km(origin, destination):
    def coords(pair):
        lat, lon = map(finite, pair)
        if not -90 <= lat <= 90 or not -180 <= lon <= 180:
            raise ValueError('invalid coordinates')
        return math.radians(lat), math.radians(lon)
    a, b = coords(origin), coords(destination)
    z = math.sin((b[0]-a[0])/2)**2 + math.cos(a[0])*math.cos(b[0])*math.sin((b[1]-a[1])/2)**2
    return 6371.0088 * 2 * math.asin(math.sqrt(min(1, max(0, z))))


def regulation_summary(row):
    """Already captured PRIOR-game data only; caller enforces context cutoff."""
    full = [finite(row['home_score']), finite(row['away_score'])]
    regulation = row.get('regulation_scores')
    possessions = row.get('regulation_possessions')
    if regulation is None or possessions is None:
        return {'settlement_scores': full, 'regulation_points_per_possession': None, 'missing': ['regulation score or possession inputs unavailable']}
    if len(regulation) != 2 or len(possessions) != 2:
        raise ValueError('two team inputs required')
    reg = list(map(finite, regulation)); poss = list(map(finite, possessions))
    if min(reg) < 0 or min(poss) <= 0 or any(r > f for r, f in zip(reg, full)):
        raise ValueError('invalid regulation inputs')
    return {'settlement_scores': full, 'regulation_points_per_possession': [r/p for r,p in zip(reg,poss)], 'regulation_possessions': poss, 'missing': []}


def shrink_offseason(state, prior, retention):
    """Explicit caller-supplied challenger setting; no arbitrary fitted default."""
    weight = finite(retention)
    if not 0 <= weight <= 1:
        raise ValueError('retention must be in [0,1]')
    if set(state) != set(prior):
        raise ValueError('state/prior fields differ')
    return {k: weight * finite(state[k]) + (1-weight) * finite(prior[k]) for k in state}


def fit_normalizer(rows, *, train_end):
    if not rows:
        raise ValueError('training rows required')
    cutoff = instant(train_end)
    for r in rows:
        if instant(r['kickoff']) > cutoff:
            raise ValueError('normalizer contains future/test rows')
        observed(r, cutoff)
    keys = set(rows[0]['features'])
    if any(set(r['features']) != keys for r in rows):
        raise ValueError('inconsistent features')
    result = {}
    for key in sorted(keys):
        values = [finite(r['features'][key]) for r in rows if r['features'][key] is not None]
        avg = mean(values) if values else None
        scale = math.sqrt(mean([(v-avg)**2 for v in values])) if values else None
        result[key] = {'mean': avg, 'scale': scale, 'observations': len(values)}
    return {'train_end': train_end, 'features': result}


def normalize(features, fitted):
    out = {}; missing = []
    for key, params in fitted['features'].items():
        value = features.get(key)
        if value is None or params['mean'] is None:
            out[key] = None; missing.append(key)
        else:
            out[key] = (finite(value)-params['mean']) / (params['scale'] or 1.)
    return {'features': out, 'missing': missing}


def fit_team_efficiency(rows, *, train_end, ridge):
    """Opponent-adjusted points/possession: intercept + offense - defense + home.

    All team effects and the home term are ridge penalized; intercept is not.
    Positive ridge identifies team effects; no default hyperparameter is selected.
    Each row is a completed game with regulation scores/possessions and cutoff receipts.
    """
    import numpy as np
    alpha = finite(ridge)
    if alpha <= 0:
        raise ValueError('strictly positive ridge required')
    cutoff = instant(train_end)
    if not rows:
        raise ValueError('training rows required')
    teams = sorted({r[k] for r in rows for k in ('home_id','away_id')})
    index = {t:i for i,t in enumerate(teams)}
    design=[]; target=[]
    for r in rows:
        observed(r, cutoff)
        if r.get('status') != 'FINAL' or not instant(r['kickoff']) < instant(r['completed_at']) <= cutoff:
            raise ValueError('training game not final before cutoff')
        if instant(r['completed_at']) > instant(r['observed_at']):
            raise ValueError('final observed before completion')
        if type(r.get('neutral')) is not bool or r['home_id'] == r['away_id']:
            raise ValueError('explicit neutral and distinct teams required')
        summary=regulation_summary(r)
        if summary['missing']:
            raise ValueError('regulation training inputs missing')
        for side,other,home in [('home_id','away_id',1),('away_id','home_id',0)]:
            x=[1.] + [0.]*(2*len(teams)) + [float(home and not r['neutral'])]
            x[1+index[r[side]]]=1.
            x[1+len(teams)+index[r[other]]]=-1.
            design.append(x)
        target.extend(summary['regulation_points_per_possession'])
    x=np.asarray(design); y=np.asarray(target)
    penalty=np.eye(x.shape[1])*alpha; penalty[0,0]=0
    coeff=np.linalg.solve(x.T@x+penalty,x.T@y)
    return {'version':VERSION,'approval':'RESEARCH_ONLY','train_end':train_end,'ridge':alpha,
        'games':len(rows),'intercept':float(coeff[0]),'home_effect':float(coeff[-1]),
        'offense':{t:float(coeff[1+i]) for t,i in index.items()},
        'defense':{t:float(coeff[1+len(teams)+i]) for t,i in index.items()}}


def predict_team_efficiency(fitted, home_id, away_id, *, neutral):
    if type(neutral) is not bool:
        raise ValueError('explicit neutral flag required')
    if any(t not in fitted['offense'] for t in (home_id,away_id)):
        return {'home_ppp':None,'away_ppp':None,'missing':['unseen team effects']}
    b=fitted['intercept']; o=fitted['offense']; d=fitted['defense']
    return {'home_ppp':b+o[home_id]-d[away_id]+(0 if neutral else fitted['home_effect']),
        'away_ppp':b+o[away_id]-d[home_id],'missing':[]}


CONTEXT_SCHEMA = {
    'weather':['stadium_id','forecast_for','forecast_issued_at','wind_mph','gust_mph','precip_probability','temperature_f','roof'],
    'coaching':['team_id','change_announced_at','effective_at','role'],
    'matchup':['team_id','window_end','sacks_allowed','dropbacks','pass_plays','offensive_plays','ol_returning_starters','ol_starter_slots'],
}


def preflight_context(event, asof, inputs):
    """Validate supplied facts; absent fields block that context, never become zero."""
    cutoff=instant(asof)
    if cutoff >= instant(event['kickoff']):
        raise ValueError('cutoff must precede game')
    out={}; blockers=[]
    for kind,fields in CONTEXT_SCHEMA.items():
        entries=inputs.get(kind)
        if not entries:
            blockers.append(kind+': unavailable'); out[kind]=[]; continue
        if kind=='weather': entries=[entries]
        accepted=[]
        for row in entries:
            missing=[f for f in fields if row.get(f) is None]
            if missing:
                blockers.append(kind+': missing '+','.join(missing)); continue
            observed(row,cutoff)
            if kind=='weather':
                if event.get('stadium_id') is None:
                    blockers.append('weather: event stadium identity unavailable'); continue
                if row['stadium_id']!=event['stadium_id'] or instant(row['forecast_for'])!=instant(event['kickoff']):
                    raise ValueError('weather stadium/time mismatch')
                if instant(row['forecast_issued_at']) > instant(row['observed_at']):
                    raise ValueError('forecast vintage after capture')
                if row['roof'] not in ('open','closed','unknown'):
                    raise ValueError('roof state invalid')
                for f in ('wind_mph','gust_mph'):
                    if finite(row[f])<0: raise ValueError('negative wind')
                if not 0<=finite(row['precip_probability'])<=1: raise ValueError('precipitation probability invalid')
                finite(row['temperature_f'])
                if row['roof']=='unknown': blockers.append('weather: roof state unknown')
            else:
                if row['team_id'] not in (event['home_id'],event['away_id']):
                    raise ValueError('context team mismatch')
                if kind=='coaching':
                    if instant(row['change_announced_at']) > instant(row['observed_at']) or instant(row['effective_at'])>cutoff:
                        raise ValueError('coaching change not known/effective')
                else:
                    if instant(row['window_end'])>=cutoff: raise ValueError('matchup window reaches forecast cutoff')
                    for f in fields[2:]:
                        if finite(row[f])<0: raise ValueError('negative workload')
                    if row['sacks_allowed']>row['dropbacks'] or row['pass_plays']>row['offensive_plays'] or row['ol_returning_starters']>row['ol_starter_slots']:
                        raise ValueError('inconsistent matchup counts')
            accepted_row = dict(row)
            if kind == 'matchup':
                accepted_row['sack_rate'] = row['sacks_allowed']/row['dropbacks'] if row['dropbacks'] else None
                accepted_row['pass_tendency'] = row['pass_plays']/row['offensive_plays'] if row['offensive_plays'] else None
                accepted_row['ol_continuity'] = row['ol_returning_starters']/row['ol_starter_slots'] if row['ol_starter_slots'] else None
                if any(accepted_row[k] is None for k in ('sack_rate','pass_tendency','ol_continuity')):
                    blockers.append('matchup: zero opportunity denominator; rates unresolved')
            accepted.append(accepted_row)
        out[kind]=accepted
        if kind!='weather':
            for team in (event['home_id'],event['away_id']):
                if not any(r['team_id']==team for r in accepted): blockers.append(kind+': team '+str(team)+' missing')
    return {'inputs':out,'blockers':blockers,'source_authentication':'caller supplied; not independently authenticated'}


def run_candidate(event, history, asof, *, contextual_inputs, training_rows=None,
                  train_end=None, ridge=None, travel=None):
    """Preflight -> measured features -> optional training-only efficiency prediction.

    Does not invent possessions, turn PPP into score probabilities, or activate wagers.
    """
    measured=context(event,history,asof,travel=travel)
    preflight=preflight_context(event,asof,contextual_inputs)
    blockers=list(preflight['blockers'])
    for team,values in measured['teams'].items():
        blockers.extend(str(team)+': '+issue for issue in values['missing_or_limitations'])
    efficiency=None
    if training_rows is None or train_end is None or ridge is None:
        blockers.append('efficiency fit requires supplied training rows, cutoff and positive ridge')
    else:
        if instant(train_end)>=instant(asof): raise ValueError('training cutoff must precede forecast')
        model=fit_team_efficiency(training_rows,train_end=train_end,ridge=ridge)
        efficiency=predict_team_efficiency(model,event['home_id'],event['away_id'],neutral=event['neutral'])
        blockers.extend(efficiency['missing'])
    blockers.append('score distribution, betting edge and production approval not established')
    return {'version':VERSION,'event_id':event['event_id'],'approval':'RESEARCH_ONLY',
        'measured_context':measured,'preflight':preflight,'efficiency_prediction':efficiency,
        'blockers':blockers,'production_approved':False,'approved_risk_usd':0}

ABLATION_PROTOCOL['arms'] = ['baseline','rest','travel','momentum_innovation',
    'opponent_adjusted_efficiency','offseason_shrink','weather','coaching','matchup_continuity']
ABLATION_PROTOCOL['restriction'] = 'one added arm at a time; hyperparameters and shrink retention fixed using training folds only'
