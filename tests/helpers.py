from datetime import timedelta
from project_craps.common import digest, envelope, now, stamp
from project_craps.train import train


def fixtures(sport='NFL'):
    issued = now() + timedelta(seconds=10)
    observed = stamp(issued - timedelta(minutes=2))
    source = {'url': 'https://example.test/synthetic.csv', 'sha256': 'fixture',
              'observed_at': observed, 'publication_time': None, 'bytes': 0}
    games = []
    def event(eid, season, kickoff, hs, aw):
        return {'event_id': eid, 'sport': sport, 'season': season, 'home_id': 'A', 'away_id': 'B',
            'home': 'Synthetic A', 'away': 'Synthetic B', 'kickoff': stamp(kickoff),
            'status': 'SCHEDULED' if hs is None else 'FINAL', 'home_score': hs, 'away_score': aw,
            'neutral': False, 'time_known': True, 'observed_at': observed,
            'source_sha256': 'fixture', 'source_url': source['url']}
    for year in range(2016, 2026):
        for week in range(8):
            kickoff = issued.replace(year=year, month=9, day=1) + timedelta(days=7*week)
            games.append(event(str(year) + '-' + str(week), year, kickoff,
                               17 + ((week * 7 + year) % 24), 13 + ((week * 11 + year) % 28)))
    games.append(event('recent', issued.year, issued - timedelta(days=7), 21, 17))
    future = event('future', issued.year, issued + timedelta(hours=2), None, None)
    games.append(future)
    snapshot = envelope({'sport': sport, 'captured_at': observed, 'sources': [source],
                         'games': sorted(games, key=lambda g: (g['kickoff'], g['event_id']))})
    model, report = train(snapshot, folds=(2022, 2023, 2024, 2025), minimum=2)
    quote = {key: future[key] for key in ('sport', 'event_id', 'home_id', 'away_id', 'kickoff')}
    quote.update(book='SYNTHETIC TEST ONLY', source_url='https://example.test/quote',
          scope='full_game_including_overtime', market='spread', selection='away', line=3,
          american_odds=-110, verified_executable=False, observed_at=observed,
          expires_at=stamp(issued + timedelta(minutes=2)))
    context = {kind: {'event_id': 'future', 'sport': sport, 'status': 'RESOLVED',
               'observed_at': observed, 'source_url': 'https://example.test/context',
               'notes': 'SYNTHETIC TEST ONLY'} for kind in ('quarterback', 'roster', 'weather')}
    return issued, model, snapshot, quote, context
