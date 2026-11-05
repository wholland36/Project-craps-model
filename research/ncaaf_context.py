"""Pregame context research; no fitted trap/momentum coefficients or live approval."""
from copy import deepcopy
from datetime import timedelta
import math
import re
from statistics import mean
from project_craps.common import instant
from project_craps.model import predict, score_distribution, outcome_masses

VERSION = 'ncaaf-context-v1-research'


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('finite numeric input required')
    return float(value)


def evidence(row, cutoff):
    if not re.fullmatch(r'[a-f0-9]{64}', row['source_sha256']):raise ValueError('source hash required')
    if not row['source_url'].startswith('https://'):raise ValueError('HTTPS source required')
    if not instant(row['published_at']) <= instant(row['observed_at']) <= cutoff:
        raise ValueError('source was unavailable at cutoff')


def validate_poll_ranks(ranks):
    """Complete AP top-25 slots, allowing competition ties (including tied25)."""
    values=list(ranks.values())
    if len(values)<25 or any(type(x) is not int or not 1<=x<=25 for x in values):
        raise ValueError('complete poll must cover all top25 slots')
    values.sort()
    for i,rank in enumerate(values):
        if (i==0 or rank!=values[i-1]) and rank!=i+1:
            raise ValueError('poll ranks must follow competition ranking with ties')


def rank_at(polls, team, cutoff):
    """None = unknown; 0 = absent from a complete AP Top 25."""
    available=[]
    for p in polls:
        if p.get('poll') != 'AP' or instant(p['observed_at']) > cutoff:continue
        evidence(p, cutoff)
        if not instant(p['effective_from']) <= cutoff < instant(p['valid_until']):continue
        if p.get('complete') is not True:continue
        ranks=p['ranks']
        validate_poll_ranks(ranks)
        available.append(p)
    if not available:return None
    latest=max(available,key=lambda p:instant(p['published_at']))
    if any(p['published_at']==latest['published_at'] and p['ranks']!=latest['ranks'] for p in available):
        raise ValueError('conflicting poll editions')
    return latest['ranks'].get(team,0)


def opponent(game, team):
    if game['home_id']==team:return game['away_id']
    if game['away_id']==team:return game['home_id']
    raise ValueError('team not in event')


def traps(event, team, schedule, polls, asof):
    """Adjacent same-season games; byes do not count as games."""
    cutoff=instant(asof)
    if cutoff >= instant(event['kickoff']):raise ValueError('target already started')
    evidence(schedule,cutoff)
    if schedule.get('complete') is not True:
        return {'status':'UNRESOLVED_SCHEDULE','before_top25':None,'after_top25':None}
    games=sorted([g for g in schedule['games'] if g['season']==event['season'] and
                  team in (g['home_id'],g['away_id']) and g.get('status')!='CANCELED'],
                 key=lambda g:instant(g['kickoff']))
    if len({g['event_id'] for g in games})!=len(games):raise ValueError('duplicate schedule event')
    matches=[i for i,g in enumerate(games) if g['event_id']==event['event_id']]
    if len(matches)!=1:raise ValueError('target missing from complete schedule')
    i=matches[0]
    if any(games[i][k]!=event[k] for k in ('kickoff','home_id','away_id')):raise ValueError('target identity changed')
    current=rank_at(polls,opponent(event,team),cutoff)
    previous=games[i-1] if i else None;following=games[i+1] if i+1<len(games) else None
    prior_rank=rank_at(polls,opponent(previous,team),instant(previous['kickoff'])-timedelta(microseconds=1)) if previous else 0
    next_rank=rank_at(polls,opponent(following,team),cutoff) if following else 0
    def flag(rank):
        if current is None:return None
        if current>0:return False
        return None if rank is None else 1<=rank<=25
    return {'status':'RESEARCH_FEATURES_ONLY','poll':'AP','opponent_rank':current,
            'previous_opponent_pregame_rank':prior_rank,'next_opponent_rank_known_at_forecast':next_rank,
            'before_top25':flag(next_rank),'after_top25':(flag(prior_rank) if previous is None or (previous.get('status')=='FINAL' and previous.get('completed_at') and instant(previous['completed_at'])<=cutoff) else None),
            'previous_event_id':previous['event_id'] if previous else None,
            'next_event_id':following['event_id'] if following else None,'learned_point_adjustment':None}


def momentum(event, team, history, asof):
    cutoff=instant(asof)
    if cutoff>=instant(event['kickoff']):raise ValueError('target already started')
    eligible=[];seen=set()
    for g in history:
        if g['event_id']==event['event_id'] or g['season']!=event['season'] or team not in (g['home_id'],g['away_id']):continue
        if g.get('status')!='FINAL' or instant(g['observed_at'])>cutoff:continue
        evidence(g,cutoff)
        if not instant(g['kickoff'])<instant(g['completed_at'])<=instant(g['observed_at']):raise ValueError('final result timing invalid')
        if g['event_id'] in seen:raise ValueError('duplicate historical event')
        seen.add(g['event_id']);eligible.append(g)
    eligible.sort(key=lambda g:instant(g['kickoff']),reverse=True)
    def window(gs):
        wins=[];margins=[];residuals=[]
        for g in gs:
            sign=1 if g['home_id']==team else -1
            margin=sign*(number(g['home_score'])-number(g['away_score']))
            margins.append(margin);wins.append(float(margin>0))
            f=g.get('pregame_expectation')
            if f:
                evidence(f,instant(g['kickoff'])-timedelta(microseconds=1))
                if f.get('market_blind') is not True or not re.fullmatch('[a-f0-9]{64}',f['model_sha256']):
                    raise ValueError('independent market-blind expectation and model hash required')
                if instant(f['trained_through'])>instant(f['published_at']):raise ValueError('expectation model trained after forecast')
                residuals.append(margin-sign*number(f['expected_home_margin']))
        return {'games':len(gs),'win_rate':mean(wins) if wins else None,'mean_margin':mean(margins) if margins else None,
                'expectation_residual_games':len(residuals),
                'mean_margin_above_expectation':mean(residuals) if len(residuals)==len(gs) and gs else None}
    recent,older=window(eligible[:3]),window(eligible[3:6]);complete=recent['games']==older['games']==3
    def change(key):return recent[key]-older[key] if complete and recent[key] is not None and older[key] is not None else None
    return {'status':'RESEARCH_FEATURES_ONLY','recent_three':recent,'previous_three':older,
            'win_rate_trend':change('win_rate'),'opponent_adjusted_margin_trend':change('mean_margin_above_expectation'),
            'opponent_adjustment':'Residual against frozen independent pregame model; missing expectations are not imputed',
            'learned_point_adjustment':None}


def injuries(event, reports, asof, *, roster_coverage_complete=False):
    """Use EXTERNAL points-over-replacement values relative to baseline availability.

    Does not estimate or validate player values; no automatic star penalty.
    """
    cutoff=instant(asof)
    if cutoff>=instant(event['kickoff']):raise ValueError('target already started')
    issues=[] if roster_coverage_complete else ['roster availability coverage incomplete']
    uncertain=False
    details=[];seen=set();deltas={t:{'for':0.,'against':0.} for t in (event['home_id'],event['away_id'])}
    for r in reports:
        if r['event_id']!=event['event_id'] or r['team_id'] not in deltas:raise ValueError('injury event/team mismatch')
        key=(r['team_id'],r['player_id'])
        if key in seen:raise ValueError('duplicate player injury')
        seen.add(key);evidence(r,cutoff)
        if cutoff>=instant(r['valid_until']):raise ValueError('stale injury status')
        status=r['status']
        if status=='OUT':probability=0.
        elif status=='AVAILABLE':probability=1.
        elif status in ('QUESTIONABLE','DOUBTFUL','LIMITED'):
            uncertain=True
            probability=r.get('expected_effective_availability')
            if probability is None:issues.append(r['player_id']+': availability unresolved');continue
            if not r.get('availability_estimate_method'):raise ValueError('availability estimate provenance required')
        else:raise ValueError('unsupported injury status')
        probability=number(probability)
        if not 0<=probability<=1:raise ValueError('availability must be between zero and one')
        value=r.get('replacement_value')
        if not value:issues.append(r['player_id']+': player versus replacement value missing');continue
        evidence(value,cutoff)
        if instant(value['trained_through'])>instant(value['published_at']) or instant(value['trained_through'])>=cutoff:raise ValueError('player value uses future training')
        if not re.fullmatch('[a-f0-9]{64}',value['model_sha256']):raise ValueError('player value model hash required')
        if not value.get('replacement_player_id'):raise ValueError('replacement identity required')
        base=number(value['baseline_effective_availability'])
        if not 0<=base<=1:raise ValueError('invalid baseline availability')
        attack=number(value['points_for_over_replacement']);defense=number(value['points_prevented_over_replacement'])
        if min(attack,defense)<0:raise ValueError('nonnegative value-over-replacement inputs required')
        change=probability-base;df,da=change*attack,-change*defense
        deltas[r['team_id']]['for']+=df;deltas[r['team_id']]['against']+=da
        details.append({'player_id':r['player_id'],'position':r['position'],'status':status,
                        'effective_availability':probability,'baseline_effective_availability':base,
                        'expected_points_for_delta':df,'expected_points_against_delta':da,
                        'replacement_player_id':value['replacement_player_id'],'value_model_sha256':value['model_sha256']})
    if issues:return {'status':'NOT_COMPUTED','issues':issues,'player_details':details,'margin_delta':None,'total_delta':None,'production_approved':False}
    h,a=deltas[event['home_id']],deltas[event['away_id']];home=h['for']+a['against'];away=a['for']+h['against']
    return {'status':'RESEARCH_SCENARIO_ONLY','issues':[], 'player_details':details,'home_score_delta':home,'away_score_delta':away,
            'margin_delta':home-away,'total_delta':home+away,'uncertain_availability':uncertain,
            'assumption':'Additive externally supplied replacement values; lineup interactions and uncertainty unvalidated','production_approved':False}


def injury_scenario(artifact, features, adjustment, market, selection, line=None):
    if artifact['sport']!='NCAAF':raise ValueError('NCAAF only')
    if adjustment['status']!='RESEARCH_SCENARIO_ONLY':raise ValueError('injury inputs unresolved')
    if adjustment.get('uncertain_availability'):raise ValueError('uncertain availability requires separate active/out scenarios, not a mean-only probability shift')
    model=deepcopy(artifact)
    model['margin']['intercept']+=number(adjustment['margin_delta']);model['total']['intercept']+=number(adjustment['total_delta'])
    scores=score_distribution(model,features)
    masses=outcome_masses(scores,market,selection,line,tie_policy='refund' if market=='moneyline' else None)
    return {'status':'RESEARCH_SCENARIO_ONLY','adjusted_mean_margin_total':predict(model,features),
            'p_win':masses[0],'p_push':masses[1],'p_loss':masses[2],'production_approved':False,'approved_risk_usd':0}


def build(event, schedule, polls, history, reports, asof, *, roster_coverage_complete=False):
    if event['sport']!='NCAAF':raise ValueError('NCAAF only')
    return {'version':VERSION,'event_id':event['event_id'],'asof':asof,'approval':'RESEARCH_ONLY',
            'home':{'trap':traps(event,event['home_id'],schedule,polls,asof),'momentum':momentum(event,event['home_id'],history,asof)},
            'away':{'trap':traps(event,event['away_id'],schedule,polls,asof),'momentum':momentum(event,event['away_id'],history,asof)},
            'injuries':injuries(event,reports,asof,roster_coverage_complete=roster_coverage_complete),
            'trap_momentum_coefficients':'NOT_FITTED','production_approved':False}


def main():
    import argparse,json
    from pathlib import Path
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    data=json.loads(args.input.read_text())
    result=build(**data)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x') as f:json.dump(result,f,indent=2,allow_nan=False)


if __name__=='__main__':main()
