"""Date-aware all-football orchestration; each sport fails independently."""
from pathlib import Path
from zoneinfo import ZoneInfo
from .common import create, instant, now, read, stamp
from .data import capture
from .pipeline import forecast
from .registry import Registry


def run(models_directory, output, registry_path, quotes_path=None, context_path=None, deliver=False):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    current = now()
    eastern_date = current.astimezone(ZoneInfo('America/New_York')).date()
    quotes = read(quotes_path) if quotes_path else {}
    contexts = read(context_path) if context_path else {}
    result = {'started_at': stamp(current), 'date_ET': str(eastern_date), 'sports': {},
              'approved_risk': 0, 'model_approval': 'RESEARCH_ONLY'}
    registry = Registry(registry_path)
    try:
        for sport in ('NFL', 'NCAAF'):
            status = {'registered': [], 'skipped_started': 0}
            result['sports'][sport] = status
            try:
                model = read(Path(models_directory) / sport / 'model.json')
                first_year = model['payload']['history_start_season']
                snapshot = capture(sport, list(range(first_year, eastern_date.year + 1)), output / sport)
                for event in snapshot['payload']['games']:
                    if instant(event['kickoff']).astimezone(ZoneInfo('America/New_York')).date() != eastern_date:
                        continue
                    if event['status'] != 'SCHEDULED' or instant(event['kickoff']) <= now():
                        status['skipped_started'] += 1
                        continue
                    key = sport + ':' + event['event_id']
                    record = forecast(model, snapshot, event['event_id'], quotes.get(key), contexts.get(key))
                    record = registry.append(record)
                    status['registered'].append({'forecast_id': record['forecast_id'], 'status': record['status'],
                                                  'reasons': record['reasons']})
                status['status'] = 'COMPLETE'
            except (OSError, ValueError, KeyError, __import__('requests').RequestException) as error:
                status['status'] = 'FAILED'
                status['error'] = str(error)
        result['registry_anchor'] = registry.verify()
        create(output / 'registry_anchor.json', result['registry_anchor'])
        if deliver:
            from .sheets import GoogleTransport, sync
            try:
                result['delivery'] = sync(registry, GoogleTransport())
            except Exception as error:
                result['delivery'] = {'status': 'FAILED', 'error_type': type(error).__name__,
                                      'pending': len(registry.pending())}
        result['completed_at'] = stamp(now())
        create(output / 'receipt.json', result)
        return result
    finally:
        registry.close()
