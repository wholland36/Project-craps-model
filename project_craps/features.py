"""Explicit allowlisted features. Quotes and target-event scores are never read."""
from itertools import groupby
from .common import instant

FEATURES = ['home_attack', 'home_defense', 'away_attack', 'away_defense',
            'elo_difference', 'home_games', 'away_games', 'home_rest', 'away_rest', 'neutral']


def initial(sport):
    base = 22.0 if sport == 'NFL' else 24.0
    return {'attack': base, 'defense': base, 'elo': 1500.0, 'n': 0, 'last_kickoff': None}


def vector(state, event):
    home = state.get(event['home_id'], initial(event['sport']))
    away = state.get(event['away_id'], initial(event['sport']))
    def rest(team):
        if team['last_kickoff'] is None:
            return 7.0
        return min(60.0, max(0.0, (instant(event['kickoff']) - instant(team['last_kickoff'])).total_seconds() / 86400))
    return [home['attack'], home['defense'], away['attack'], away['defense'],
            home['elo'] - away['elo'], home['n'], away['n'], rest(home), rest(away), float(event['neutral'])]


def update(state, event):
    home = state.setdefault(event['home_id'], initial(event['sport']))
    away = state.setdefault(event['away_id'], initial(event['sport']))
    hs, aw = event['home_score'], event['away_score']
    expectation = 1 / (1 + 10 ** ((away['elo'] - home['elo']) / 400))
    change = 20 * ((1 if hs > aw else 0 if hs < aw else .5) - expectation)
    home['elo'] += change
    away['elo'] -= change
    rate = .16 if event['sport'] == 'NFL' else .15
    for team, scored, conceded in ((home, hs, aw), (away, aw, hs)):
        team['attack'] = (1 - rate) * team['attack'] + rate * scored
        team['defense'] = (1 - rate) * team['defense'] + rate * conceded
        team['n'] += 1
        team['last_kickoff'] = event['kickoff']


def historical_features(games):
    """Batch by UTC kickoff day. Retrospective research, not verified historical PIT."""
    state, rows = {}, []
    ordered = sorted((g for g in games if g['status'] == 'FINAL'), key=lambda g: (g['kickoff'], g['event_id']))
    for _, day in groupby(ordered, key=lambda g: instant(g['kickoff']).date()):
        group = list(day)
        rows.extend((g, vector(state, g)) for g in group)
        for game in group:
            update(state, game)
    return rows, state


def live_features(games, event, issued):
    state = {}
    for game in sorted(games, key=lambda g: (g['kickoff'], g['event_id'])):
        if game['sport'] != event['sport']:
            raise ValueError('mixed sports in history')
        if game['event_id'] == event['event_id'] or game['status'] != 'FINAL':
            continue
        if instant(game['observed_at']) > issued:
            raise ValueError('history observed after forecast')
        if instant(game['kickoff']) >= issued:
            raise ValueError('future final result')
        update(state, game)
    features = vector(state, event)
    return features, state
