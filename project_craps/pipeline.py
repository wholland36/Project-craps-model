"""As-of research inference. Completeness failures persist PASS with no numeric p."""
from zoneinfo import ZoneInfo
from models.probability import price_metrics
from .common import canonical, digest, fresh, instant, now, stamp, unwrap
from .features import live_features
from .model import outcome_masses, score_distribution, validate_artifact

CONTEXT_KINDS = ('quarterback', 'roster', 'weather')


def forecast(model_wrapper, snapshot_wrapper, event_id, quote=None, context=None, clock=now):
    issued = clock()
    snapshot = unwrap(snapshot_wrapper)
    sport = snapshot['sport']
    model = validate_artifact(model_wrapper, sport)
    if instant(model['built_at']) > issued or instant(model['calibration_last_kickoff']) >= issued:
        raise ValueError('model built/calibrated after issuance')
    events = [g for g in snapshot['games'] if g['event_id'] == event_id]
    if len(events) != 1:
        raise ValueError('event ID missing or duplicated')
    event = events[0]
    if event['sport'] != sport or event['status'] != 'SCHEDULED' or instant(event['kickoff']) <= issued:
        raise ValueError('event is not a matching future scheduled game')
    identity = {key: event[key] for key in ('sport', 'event_id', 'home_id', 'away_id', 'home', 'away', 'kickoff')}
    request_key = digest({'model': model_wrapper['sha256'], 'snapshot': snapshot_wrapper['sha256'],
                          'event': identity, 'quote': quote, 'context': context})
    result = {'schema_version': 1, 'model_version': model['version'], 'model_sha256': model_wrapper['sha256'],
              'snapshot_sha256': snapshot_wrapper['sha256'], 'request_key': request_key,
              'forecast_id': 'PCR-' + request_key, 'sport': sport, 'event_id': event_id,
              'identity': identity, 'home': event['home'], 'away': event['away'],
              'kickoff': event['kickoff'], 'issued_at': stamp(issued),
              'issued_at_ET': issued.astimezone(ZoneInfo('America/New_York')).isoformat(),
              'event_date_ET': instant(event['kickoff']).astimezone(ZoneInfo('America/New_York')).date().isoformat(),
              'source_url': event['source_url'], 'data_vintage': snapshot['captured_at'],
              'historical_point_in_time_verified': False, 'model_approved': False,
              'qualification': 'PASS', 'approved_risk': 0, 'user_confirmed_placed': False,
              'status': 'BLOCKED', 'probabilities': None, 'price_metrics': None,
              'uncertainty': 'NOT_VALIDATED', 'reasons': [], 'quote': quote,
              'context_sha256': digest(context), 'feature_sha256': None, 'distribution_sha256': None}
    def reject(reason):
        result['reasons'].append(str(reason))
    try:
        fresh(snapshot['captured_at'], issued, 12 * 3600, 'score/schedule snapshot')
        fresh(event['observed_at'], issued, 12 * 3600, 'event observation')
        for source in snapshot['sources']:
            fresh(source['observed_at'], issued, 12 * 3600, 'source observation')
        if not event['time_known']:
            raise ValueError('kickoff time unconfirmed')
        if min(g['season'] for g in snapshot['games']) != model['history_start_season']:
            raise ValueError('history start does not match fitted feature state')
        if context is None:
            raise ValueError('quarterback, roster and weather context missing')
        for kind in CONTEXT_KINDS:
            item = context.get(kind)
            if not item or item.get('status') != 'RESOLVED' or not item.get('source_url') or not item.get('notes'):
                raise ValueError(kind + ' context unresolved')
            if item.get('event_id') != event_id or item.get('sport') != sport:
                raise ValueError(kind + ' context identity mismatch')
            fresh(item['observed_at'], issued, 6 * 3600, kind)
        if quote is None:
            raise ValueError('matching timestamped quote missing')
        for key in ('sport', 'event_id', 'home_id', 'away_id', 'kickoff'):
            if quote.get(key) != identity[key]:
                raise ValueError('quote identity mismatch: ' + key)
        if not quote.get('book') or not quote.get('source_url') or quote.get('scope') != 'full_game_including_overtime':
            raise ValueError('book/source/full-game settlement scope missing')
        if type(quote.get('verified_executable')) is not bool:
            raise ValueError('quote executable flag required')
        fresh(quote['observed_at'], issued, 300, 'quote')
        if not (issued < instant(quote['expires_at']) <= instant(event['kickoff'])):
            raise ValueError('expired quote or invalid cutoff')
        features, state = live_features([g for g in snapshot['games'] if g['season'] >= model['history_start_season']], event, issued)
        if features[5] < 8 or features[6] < 8:
            raise ValueError('insufficient observed team history')
        scores = score_distribution(model, features)
        win, push, loss = outcome_masses(scores, quote['market'], quote['selection'], quote.get('line'), quote.get('tie_policy'))
        metrics = price_metrics(win, push, loss, quote['american_odds'])
        conditional = metrics['win_conditional_nonpush']
        metrics['edge_conditional_nonpush'] = conditional - metrics['break_even_conditional_nonpush'] if conditional is not None else None
        result.update(status='EXPERIMENTAL', probabilities={'win': win, 'push': push, 'loss': loss},
                      price_metrics=metrics, feature_sha256=digest(features), distribution_sha256=digest(scores),
                      features=features, score_support=scores, quote_cutoff=quote['expires_at'])
        reject('research challenger has no wagering approval or validated uncertainty')
        if not quote['verified_executable']:
            reject('book quote is a reference; account execution unverified')
    except (ValueError, KeyError, TypeError) as error:
        reject(error)
    return result
