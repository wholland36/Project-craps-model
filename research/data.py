"""Hash-archived public efficiency and roster sources. No paid requests/retries."""
import csv
import io
import json
import math
from pathlib import Path
import requests
import pyarrow.parquet as parquet
from project_craps.common import bytes_hash, create, digest, envelope, instant, now, stamp, unwrap

NFL = 'https://github.com/nflverse/nflverse-data/releases/download/stats_team/stats_team_week_{year}.csv'
CFB = 'https://github.com/sportsdataverse/sportsdataverse-data/releases/download/cfb_team_summaries_weekly/cfb_team_summaries_weekly_{year}.parquet'
ANNUAL = 'https://github.com/sportsdataverse/sportsdataverse-data/releases/download/{tag}/{tag}_{year}.parquet'


def number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def fetch(url, directory, label):
    response = requests.get(url, timeout=90)
    response.raise_for_status()  # No automatic paid/free retry.
    observed = stamp(now())
    sha = bytes_hash(response.content)
    suffix = '.parquet' if url.endswith('.parquet') else '.csv'
    path = directory / (sha + suffix)
    if not path.exists():
        path.write_bytes(response.content)
    manifest = {'url': url, 'sha256': sha, 'file': path.name, 'observed_at': observed,
                'original_publication_at': None, 'label': label, 'bytes': len(response.content)}
    create(directory / (label + '.json'), manifest)
    return manifest


def raw_rows(directory, source):
    raw = (Path(directory) / source['file']).read_bytes()
    if bytes_hash(raw) != source['sha256']:
        raise ValueError('efficiency source hash mismatch')
    if source['file'].endswith('.parquet'):
        return parquet.read_table(io.BytesIO(raw)).to_pylist()
    return list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))


def capture(sport, years, output, annual=True):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    sources, failures = [], []
    for year in years:
        try:
            sources.append(fetch((NFL if sport == 'NFL' else CFB).format(year=year), output, str(year)))
        except requests.RequestException as error:
            failures.append({'season': year, 'error_type': type(error).__name__, 'scope': 'efficiency'})
        if sport == 'NCAAF' and annual:
            for tag in ('cfb_returning_production', 'cfb_team_portal'):
                try:
                    sources.append(fetch(ANNUAL.format(tag=tag, year=year), output, tag + '-' + str(year)))
                except requests.RequestException as error:
                    failures.append({'season': year, 'error_type': type(error).__name__, 'scope': tag})
    result = envelope({'sport': sport, 'captured_at': stamp(now()), 'years': list(years),
                       'sources': sources, 'failures': failures,
                       'historical_publication_verified': False,
                       'annual_feature_policy': 'Archive only; historical numeric use blocked without original availability evidence'})
    create(output / 'manifest.json', result)
    return result


def load(path):
    path = Path(path)
    wrapper = json.loads(path.read_text())
    payload = unwrap(wrapper)
    for source in payload['sources']:
        if bytes_hash((path.parent / source['file']).read_bytes()) != source['sha256']:
            raise ValueError('raw source hash mismatch')
    return wrapper


def nfl_metrics(rows):
    result = {}
    required = {'game_id', 'team', 'season_type', 'attempts', 'carries', 'sacks_suffered',
                'passing_epa', 'rushing_epa', 'passing_interceptions', 'fumbles_lost_total',
                'passing_20', 'rushing_10'}
    for row in rows:
        if not required.issubset(row):
            raise ValueError('NFL efficiency schema drift')
        if row['season_type'] != 'REG':
            continue
        attempts, carries, sacks = (number(row[k]) for k in ('attempts', 'carries', 'sacks_suffered'))
        if any(x is None for x in (attempts, carries, sacks)):
            continue
        plays = attempts + carries + sacks
        if plays <= 0 or attempts + sacks <= 0:
            continue
        def ratio(keys, denominator):
            values = [number(row[k]) for k in keys]
            return sum(values) / denominator if all(x is not None for x in values) else None
        values = {'epa': ratio(['passing_epa', 'rushing_epa'], plays),
                  'volume': plays, 'turnovers': ratio(['passing_interceptions', 'fumbles_lost_total'], plays),
                  'disruption': sacks / (attempts + sacks),
                  'explosive': ratio(['passing_20', 'rushing_10'], plays)}
        key = (str(row['game_id']), str(row['team']))
        if key in result:
            raise ValueError('duplicate NFL game/team statistics')
        result[key] = values
    return result


def cfb_metrics(rows):
    result = {}
    keys = ['EPAplay_off', 'playsgame_off', 'turnovers_off', 'havoc_off', 'explosive_off',
            'EPAplay_def', 'playsgame_def', 'turnovers_def', 'havoc_def', 'explosive_def']
    for row in rows:
        if not {'team_id', 'season', 'through_week', *keys}.issubset(row):
            raise ValueError('FBS weekly efficiency schema drift')
        week, year = int(row['through_week']), int(row['season'])
        team = str(int(row['team_id']))
        key = (year, team, week)
        if key in result:
            raise ValueError('duplicate FBS team/week summary')
        result[key] = {k: number(row[k]) for k in keys}
    return result


def schedule_metadata(snapshot_wrapper, directory):
    """Recover only identity/week metadata; market lines are diagnostic-only."""
    metadata, week_deadlines = {}, {}
    games_by_id = {g['event_id']: g for g in snapshot_wrapper['payload']['games']}
    from datetime import timedelta
    for source in snapshot_wrapper['payload']['sources']:
        raw = (Path(directory) / (source['sha256'] + '.csv')).read_bytes()
        if bytes_hash(raw) != source['sha256']:
            raise ValueError('schedule bytes changed')
        for row in csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))):
            eid = str(row['game_id'])
            if eid not in games_by_id:
                continue
            game = games_by_id[eid]
            metadata[eid] = {'week': int(row['week']), 'spread_home_margin': number(row.get('spread_line')),
                'total_line': number(row.get('total_line')), 'neutral': game['neutral'],
                'scope': row.get('season_type', row.get('game_type')),
                'overtime': bool(number(row.get('overtime'))) if number(row.get('overtime')) is not None else None,
                'espn_event_id': str(row.get('espn') or eid)}
            if snapshot_wrapper['payload']['sport'] == 'NCAAF' and row.get('season_type') == 'regular':
                key = (game['season'], int(row['week']))
                cutoff = instant(game['kickoff']) + timedelta(hours=48)
                week_deadlines[key] = max(week_deadlines.get(key, cutoff), cutoff)
    return metadata, week_deadlines
