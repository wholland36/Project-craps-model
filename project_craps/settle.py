"""Grade only previously registered research forecasts; no wager settlement."""
import math
from .common import digest, instant, now, stamp, unwrap
from .model import outcome_masses


def settle(registry, snapshot_wrapper, clock=now):
    snapshot = unwrap(snapshot_wrapper)
    observed = clock()
    by_id = {g['event_id']: g for g in snapshot['games']}
    results = []
    for record in registry.rows():
        if record['sport'] != snapshot['sport']:
            continue
        event = by_id.get(record['event_id'])
        if not event or event['status'] != 'FINAL':
            continue
        identity = {key: event[key] for key in record['identity']}
        if identity != record['identity']:
            raise ValueError('settlement event identity/kickoff changed; quarantine required')
        if not (instant(record['issued_at']) < instant(event['kickoff']) < instant(event['observed_at']) <= observed):
            raise ValueError('invalid prospective settlement timestamps')
        outcome, brier, logloss = None, None, None
        eligible = record['probabilities'] is not None and record['status'] == 'EXPERIMENTAL'
        if eligible:
            quote = record['quote']
            outcome = outcome_masses([(event['home_score'], event['away_score'])], quote['market'],
                                      quote['selection'], quote.get('line'), quote.get('tie_policy'))
            p = [record['probabilities'][k] for k in ('win', 'push', 'loss')]
            brier = sum((a - b) ** 2 for a, b in zip(p, outcome))
            logloss = -sum(t * math.log(max(1e-9, probability)) for probability, t in zip(p, outcome))
        receipt = {'forecast_id': record['forecast_id'], 'event_result': {
            'identity': identity, 'home_score': event['home_score'], 'away_score': event['away_score']},
            'settled_at': stamp(observed), 'result_observed_at': event['observed_at'],
            'source_snapshot_sha256': snapshot_wrapper['sha256'], 'source_url': event['source_url'],
            'calibration_eligible_research': eligible, 'first_event_forecast': record['first_forecast_id'] == record['forecast_id'],
            'outcome_wpl': outcome, 'threeway_brier': brier, 'threeway_logloss': logloss,
            'official_risk': 0, 'official_pnl': 0,
            'warning': 'Research only. Revisions and markets on one event are correlated. No original probability backfill.'}
        results.append(registry.settle_research(receipt))
    return results
