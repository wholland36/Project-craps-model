"""Causal-order opponent/efficiency challengers; historical source vintage unknown."""
from collections import defaultdict
from copy import deepcopy
from itertools import groupby
import csv
from pathlib import Path
import re
from project_craps.common import instant
from project_craps.features import FEATURES, historical_features
from .data import number

METRICS = ['epa', 'volume', 'turnovers', 'disruption', 'explosive']
SCORE_FEATURES = [side+'_'+kind for side in ('home', 'away') for kind in ('adjusted_attack', 'adjusted_defense')]
EXTRA_FEATURES = [side+'_'+role+'_'+metric for side in ('home','away') for role in ('off','def') for metric in METRICS]
EXTRA_FEATURES += [side+'_opponent_adjusted_epa_'+role for side in ('home','away') for role in ('off','def')]
EXTRA_FEATURES += [side+'_efficiency_coverage' for side in ('home','away')]


def feature_names(variant):
    return FEATURES + (SCORE_FEATURES if variant in ('opponent_score','efficiency','score_kernel') else []) + (EXTRA_FEATURES if variant in ('efficiency','score_kernel') else [])


def defaults(sport):
    return {'epa': 0., 'volume': 64. if sport=='NFL' else 70., 'turnovers': .025,
            'disruption': .06, 'explosive': .12}


def norm(name):
    return re.sub('[^a-z0-9]', '', name.lower())


def player_sacks(directory, sources, games):
    by_id = {g['event_id']: g for g in games}
    counts = defaultdict(lambda: [0,0])
    matched_plays=0
    rejected = 0
    for source in sources:
        seen=set()
        with (Path(directory)/source['file']).open() as stream:
            reader = csv.DictReader(stream)
            if not {'game_id','play_id','team','opponent','sack_taken_stat','sack_taken_player_id'}.issubset(reader.fieldnames or []):
                raise ValueError('FBS attributed play schema drift')
            for row in reader:
                event = by_id.get(str(row['game_id']))
                if event is None:
                    continue
                matches = [role for role in ('home','away') if norm(row['team']) == norm(event[role])]
                if len(matches) != 1:
                    opponent = [role for role in ('home','away') if norm(row['opponent']) == norm(event[role])]
                    matches = [('away' if opponent[0]=='home' else 'home')] if len(opponent)==1 else []
                if len(matches) != 1:
                    rejected += 1
                    continue
                role = matches[0]
                key = (str(row['game_id']), str(row['play_id']), event[role+'_id'])
                if key in seen:
                    continue
                seen.add(key)
                matched_plays+=1
                dropback = any(row.get(k) not in (None,'','NA') for k in
                    ('completion_player_id','incompletion_player_id','interception_thrown_player_id','sack_taken_player_id'))
                sacks = number(row.get('sack_taken_stat'))
                sacks = sacks if sacks is not None else number(row.get('sack_stat'))
                if dropback or (sacks is not None and sacks > 0):
                    counts[(event['event_id'],event[role+'_id'])][1] += 1
                    counts[(event['event_id'],event[role+'_id'])][0] += int(sacks is not None and sacks>0)
    return {k:v[0]/v[1] for k,v in counts.items() if v[1]>0}, {'unmatched_player_rows':rejected,'matched_unique_plays':matched_plays}


def build(games, metadata, weekly_deadlines, nfl=None, cfb=None, sack_rates=None, future_targets=None, asof=None):
    sport = games[0]['sport']
    baseline_rows,_ = historical_features(games)
    baseline = {g['event_id']:x for g,x in baseline_rows}
    finals = [g for g,x in baseline_rows]
    if future_targets:
        if asof is None:raise ValueError('as-of time required for prospective features')
        from project_craps.features import live_features
        for event in future_targets:
            if event['status']!='SCHEDULED' or instant(event['kickoff'])<=asof:raise ValueError('prospective target not pregame')
            baseline[event['event_id']]=live_features(games,event,asof)[0]
        finals=sorted(finals+list(future_targets),key=lambda g:(g['kickoff'],g['event_id']))
    score_state = {}
    metric_state = {}
    opponents = defaultdict(list)
    weekly_index = defaultdict(list)
    for (year,team,week),values in (cfb or {}).items():
        cutoff = weekly_deadlines.get((year,week))
        if cutoff:
            weekly_index[(year,team)].append((cutoff,values,week))
    for key in weekly_index:
        weekly_index[key].sort(key=lambda x:x[0])
    base = 22. if sport=='NFL' else 24.
    def score(team):
        return score_state.setdefault(team, {'attack':base,'defense':base})
    def metrics(team):
        return metric_state.setdefault(team, {'off':defaults(sport),'def':defaults(sport),'adjusted_off':0.,'adjusted_def':0.,'n':0,'sack_n':0})
    def raw(team, event):
        if sport=='NFL':
            return deepcopy(metrics(team)), None
        candidates = [x for x in weekly_index.get((event['season'],team),[]) if x[0] < (min(instant(event['kickoff']),asof) if asof is not None else instant(event['kickoff']))]
        result = {'off':defaults(sport),'def':defaults(sport),'n':0}
        if not candidates:
            return result, None
        cutoff, values, week = candidates[-1]
        for role in ('off','def'):
            result[role].update({'epa':values['EPAplay_'+role], 'volume':values['playsgame_'+role],
                'turnovers': (values['turnovers_'+role]/values['playsgame_'+role]) if values['turnovers_'+role] is not None and values['playsgame_'+role] else None,
                'explosive':values['explosive_'+role]})
            # Actual sacks from separate attributed play records; havoc is not relabeled sacks.
            result[role]['disruption'] = metrics(team)[role]['disruption']
            for key in METRICS:
                if result[role][key] is None:
                    result[role][key] = defaults(sport)[key]
        result['n'] = 1 if metrics(team)['sack_n'] and all(values[k] is not None for k in ('EPAplay_off','EPAplay_def','playsgame_off','playsgame_def')) else 0
        return result, cutoff.isoformat()
    output=[]
    for day,group in groupby(finals,key=lambda g:instant(g['kickoff']).date()):
        batch=list(group)
        changes=[]
        for game in batch:
            h,a = game['home_id'],game['away_id']
            hs,aw = score(h).copy(),score(a).copy()
            adjusted = [hs['attack'],hs['defense'],aw['attack'],aw['defense']]
            extra=[]; priors=[]; cuts=[]
            for team in (h,a):
                values,cut=raw(team,game);cuts.append(cut)
                extra.extend(values[role][metric] for role in ('off','def') for metric in METRICS)
                priors.append(values)
            adj_epa=[]
            for team,values in zip((h,a),priors):
                if sport=='NFL':
                    adj_epa.extend([values['adjusted_off'],values['adjusted_def']])
                else:
                    faced=[raw(opp,game)[0] for opp in opponents[(game['season'],team)]]
                    faced=[v for v in faced if v['n']]
                    adj_epa.extend([values['off']['epa']-sum(v['def']['epa'] for v in faced)/len(faced) if faced else 0.,
                                    values['def']['epa']-sum(v['off']['epa'] for v in faced)/len(faced) if faced else 0.])
            extra+=adj_epa+[float(v['n']>0) for v in priors]
            bx=baseline[game['event_id']]
            output.append({'game':game,'features':{'original':bx,'scaled':bx,
                 'opponent_score':bx+adjusted,'efficiency':bx+adjusted+extra,'score_kernel':bx+adjusted+extra},
                 'metadata':metadata.get(game['event_id'],{}),'stat_cutoffs':cuts,
                 'efficiency_complete':all(v['n']>0 for v in priors)})
            if game['status']=='FINAL':changes.append((game,hs,aw,priors))
        for game,hs,aw,prior_metrics in changes:
            h,a=game['home_id'],game['away_id']
            for team,points,allowed,opp_prior in ((h,game['home_score'],game['away_score'],aw),(a,game['away_score'],game['home_score'],hs)):
                state=score(team)
                state['attack']=.85*state['attack']+.15*(points-opp_prior['defense']+base)
                state['defense']=.85*state['defense']+.15*(allowed-opp_prior['attack']+base)
            if sport=='NFL':
                aliases={'OAK':'LV','SD':'LAC','STL':'LA','LAR':'LA'}
                hm=(nfl or {}).get((game['event_id'],aliases.get(h,h))); am=(nfl or {}).get((game['event_id'],aliases.get(a,a)))
                if hm and am:
                    for i,(team,own,opponent) in enumerate(((h,hm,am),(a,am,hm))):
                        state=metrics(team);opp_prior=prior_metrics[1-i]
                        for role,values in [('off',own),('def',opponent)]:
                            for key,value in values.items():
                                if value is not None:
                                    state[role][key]=.8*state[role][key]+.2*value
                        state['adjusted_off']=.8*state['adjusted_off']+.2*(own['epa']-opp_prior['def']['epa']) if own['epa'] is not None else state['adjusted_off']
                        state['adjusted_def']=.8*state['adjusted_def']+.2*(opponent['epa']-opp_prior['off']['epa']) if opponent['epa'] is not None else state['adjusted_def']
                        state['n']+=1
            else:
                for team,other in ((h,a),(a,h)):
                    own=(sack_rates or {}).get((game['event_id'],team))
                    opp=(sack_rates or {}).get((game['event_id'],other))
                    if own is not None:metrics(team)['off']['disruption']=.8*metrics(team)['off']['disruption']+.2*own
                    if opp is not None:metrics(team)['def']['disruption']=.8*metrics(team)['def']['disruption']+.2*opp
                    if own is not None and opp is not None:metrics(team)['sack_n']+=1
                    opponents[(game['season'],team)].append(other)
    return output
