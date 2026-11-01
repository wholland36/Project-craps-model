"""Free public score/schedule captures. No paid requests, no inferred odds."""
import csv
import io
from pathlib import Path
from zoneinfo import ZoneInfo
import requests
from .common import SPORTS, bytes_hash, create, envelope, instant, now, stamp, unwrap

NFL_URL = 'https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv'
NCAA_URL = 'https://raw.githubusercontent.com/sportsdataverse/cfbfastR-data/main/schedules/csv/cfb_schedules_{year}.csv'


def capture(sport, years, output):
    if sport not in SPORTS:
        raise ValueError('unsupported sport')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    sources, games = [], []
    urls = [NFL_URL] if sport == 'NFL' else [NCAA_URL.format(year=y) for y in years]
    for url in urls:
        response = requests.get(url, timeout=90)  # Deliberately no automatic retry.
        response.raise_for_status()
        captured = stamp(now())
        sha = bytes_hash(response.content)
        raw = output / (sha + '.csv')
        if not raw.exists():
            raw.write_bytes(response.content)
        source = {'url': url, 'sha256': sha, 'observed_at': captured,
                  'publication_time': None, 'bytes': len(response.content)}
        sources.append(source)
        games.extend(normalize(sport, response.content, source, years))
    ids = [g['event_id'] for g in games]
    if len(set(ids)) != len(ids):
        raise ValueError('duplicate event IDs in captured sources')
    payload = {'sport': sport, 'captured_at': stamp(now()), 'sources': sources,
               'provenance': 'OBSERVED_NOW; historical publication times unknown',
               'games': sorted(games, key=lambda g: (g['kickoff'], g['event_id']))}
    result = envelope(payload)
    create(output / 'snapshot.json', result)
    return result


def normalize(sport, content, source, years):
    rows = csv.DictReader(io.StringIO(content.decode('utf-8-sig')))
    needed = {'game_id', 'season', 'home_team', 'away_team'}
    needed |= ({'game_type', 'gameday', 'gametime', 'home_score', 'away_score', 'location'}
               if sport == 'NFL' else
               {'start_date', 'start_time_tbd', 'completed', 'neutral_site', 'home_id',
                'away_id', 'home_points', 'away_points', 'home_division', 'away_division'})
    if not needed.issubset(rows.fieldnames or []):
        raise ValueError('source schema drift: ' + str(sorted(needed - set(rows.fieldnames or []))))
    def score(value):
        if value in ('', 'NA', None):
            return None
        result = float(value)
        if not result.is_integer() or result < 0:
            raise ValueError('invalid score')
        return int(result)
    output = []
    for row in rows:
        year = int(row['season'])
        if year not in years:
            continue
        if sport == 'NFL' and row['game_type'] != 'REG':
            continue
        if sport == 'NCAAF' and (row['home_division'] != 'fbs' or row['away_division'] != 'fbs'):
            continue
        if sport == 'NFL':
            known = bool(row['gametime'])
            date = row['gameday'] + 'T' + (row['gametime'] or '00:00')
            from datetime import datetime
            kickoff = stamp(datetime.fromisoformat(date).replace(tzinfo=ZoneInfo('America/New_York')))
            home_score, away_score = score(row['home_score']), score(row['away_score'])
            completed = home_score is not None and away_score is not None
            neutral = row['location'].lower() == 'neutral'
        else:
            known = row['start_time_tbd'].lower() == 'false'
            kickoff = stamp(instant(row['start_date']))
            home_score, away_score = score(row['home_points']), score(row['away_points'])
            completed = row['completed'].lower() == 'true'
            neutral = row['neutral_site'].lower() == 'true'
        if completed and (home_score is None or away_score is None):
            raise ValueError('final event missing scores')
        if completed and instant(kickoff) >= instant(source['observed_at']):
            raise ValueError('future result in source')
        event = {'event_id': str(row['game_id']), 'sport': sport, 'season': year,
                 'home_id': str(row.get('home_id', row['home_team'])),
                 'away_id': str(row.get('away_id', row['away_team'])),
                 'home': row['home_team'], 'away': row['away_team'],
                 'kickoff': kickoff, 'time_known': known, 'neutral': neutral,
                 'status': 'FINAL' if completed else 'SCHEDULED',
                 'home_score': home_score if completed else None,
                 'away_score': away_score if completed else None,
                 'observed_at': source['observed_at'], 'source_sha256': source['sha256'],
                 'source_url': source['url']}
        if not event['home_id'] or not event['away_id'] or event['home_id'] == event['away_id']:
            raise ValueError('invalid team identity')
        output.append(event)
    return output


def load_snapshot(path):
    path = Path(path)
    wrapper = __import__('json').loads(path.read_text())
    payload = unwrap(wrapper)
    for source in payload['sources']:
        raw = path.parent / (source['sha256'] + '.csv')
        if bytes_hash(raw.read_bytes()) != source['sha256']:
            raise ValueError('raw source hash mismatch')
    # Rebuild canonical game rows from archived bytes; reject modified normalized data.
    years = sorted(set(g['season'] for g in payload['games']))
    rebuilt = []
    for source in payload['sources']:
        rebuilt.extend(normalize(payload['sport'], (path.parent / (source['sha256'] + '.csv')).read_bytes(), source, years))
    if sorted(rebuilt, key=lambda g: (g['kickoff'], g['event_id'])) != payload['games']:
        raise ValueError('normalized rows do not match raw sources')
    return wrapper
