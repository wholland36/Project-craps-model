"""Research-only roster availability contracts; no scoring-point conversion or Elo edits."""
from datetime import datetime
import math


def _time(value):
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise ValueError('timezone required')
    return dt


def _known_before(record, cutoff):
    cut = _time(cutoff)
    try:
        return all(record.get(k) and _time(record[k]) <= cut for k in ('published_at', 'observed_at'))
    except (ValueError, TypeError, AttributeError):
        return False


def administrative_status(player_id, report, policy, cutoff):
    """Omission is meaningful only inside an attested, fully scoped report universe."""
    unknown = {'status': 'Unknown', 'derived': False, 'full_workload_verified': False}
    reasons = []
    if not report.get('authenticated') or not _known_before(report, cutoff):
        reasons.append('source_or_pregame_clock_unverified')
    if not report.get('complete'):
        reasons.append('report_not_complete')
    if player_id not in report.get('eligible_roster_ids', []):
        reasons.append('eligible_roster_unverified')
    if not report.get('roster_authenticated') or not report.get('roster_complete'):
        reasons.append('roster_coverage_unverified')
    if not policy.get('authenticated') or not _known_before(policy, cutoff):
        reasons.append('policy_unverified')
    for field in ('conference', 'season'):
        if report.get(field) != policy.get(field) or report.get(field) is None:
            reasons.append('policy_' + field + '_mismatch')
    if not report.get('conference_game') or not report.get('covered_game'):
        reasons.append('game_not_covered')
    if not report.get('kickoff'):
        return dict(unknown, missing_flags=reasons + ['kickoff_unknown'])
    if not policy.get('effective_from') or not policy.get('effective_to'):
        reasons.append('policy_window_unknown')
    elif not (_time(policy['effective_from']) <= _time(report['kickoff']) <= _time(policy['effective_to'])):
        reasons.append('outside_policy_window')
    if _time(cutoff) >= _time(report['kickoff']):
        reasons.append('cutoff_not_pregame')
    if reasons:
        return dict(unknown, missing_flags=reasons)
    explicit = report.get('statuses', {}).get(player_id)
    if explicit in ('Available', 'Out', 'Questionable', 'Doubtful'):
        return {'status': explicit, 'derived': False, 'missing_flags': [], 'full_workload_verified': False}
    if explicit is not None:
        return dict(unknown, missing_flags=['unsupported_explicit_status'])
    if policy.get('omission_means_available') is not True:
        return dict(unknown, missing_flags=['omission_policy_not_available'])
    return {'status': 'Available', 'derived': True, 'missing_flags': [], 'full_workload_verified': False}


def valid_role(player, cutoff):
    """Verified role/identity and point-in-time rating/workload; zero is a valid workload."""
    flags = []
    for key in ('identity_verified', 'role_verified', 'workload_verified'):
        if player.get(key) is not True:
            flags.append(key + '_missing')
    if not _known_before(player, cutoff):
        flags.append('role_or_rating_clock_unverified')
    for key, lo, hi in (('rating', 0, 99), ('workload', 0, 1)):
        v = player.get(key)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not lo <= v <= hi:
            flags.append(key + '_invalid')
    if not player.get('player_id') or not player.get('team') or not player.get('position') or not player.get('rating_iteration'):
        flags.append('identity_scope_incomplete')
    return flags


def allocate_replacements(losses, roster, cutoff):
    """Greedy documented depth allocation, one backup per position-slot capacity.

    PRIMARY priors are independent per injury. Exclusive reservation is a separate
    depletion sensitivity scenario. Verified actual replacements take priority.
    Otherwise non-QBs receive the mean
    of up to three strictly lower-rated eligible teammates. Pools are reserved,
    preventing the same proxy being spent on two losses. This conservative fallback
    is a research approximation, not a claim about an actual coaching rotation.
    """
    ids = [r.get('player_id') for r in roster]
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate roster identity')
    by_id = {r['player_id']: r for r in roster}
    unavailable = {r['player_id'] for r in roster if r.get('status') != 'Available'}
    unavailable |= {r['player_id'] for r in losses}
    used = set()
    results = []
    ordered = sorted(losses, key=lambda r: (not bool(r.get('actual_replacement_verified')), -r.get('rating', 0), r.get('player_id', '')))
    for loss in ordered:
        flags = valid_role(loss, cutoff)
        actual = loss.get('actual_replacement_id')
        primary = []
        if not flags and loss['position'] != 'QB':
            primary = sorted((r for r in roster if not valid_role(r, cutoff) and r['team'] == loss['team'] and r['position'] == loss['position'] and r['rating_iteration'] == loss['rating_iteration'] and r['player_id'] not in unavailable and r['rating'] < loss['rating']), key=lambda r: (-r['rating'], r['player_id']))[:3]
        method = None
        candidates = []
        def compatible(r):
            return (not valid_role(r, cutoff) and r['team'] == loss['team'] and r['position'] == loss['position']
                    and r['rating_iteration'] == loss['rating_iteration'] and r['player_id'] not in unavailable | used)
        if not flags and actual and loss.get('actual_replacement_verified'):
            r = by_id.get(actual)
            if not loss.get('replacement_published_at') or not loss.get('replacement_observed_at') or any(_time(loss[k]) > _time(cutoff) for k in ('replacement_published_at', 'replacement_observed_at')):
                flags.append('actual_replacement_clock_unverified')
            elif r is None or not compatible(r):
                flags.append('actual_replacement_ineligible_or_capacity_used')
            else:
                candidates = [r]; method = 'VERIFIED_ACTUAL'
        elif not flags and loss['position'] == 'QB':
            flags.append('qb_replacement_unverified')
        elif not flags:
            candidates = sorted((r for r in roster if compatible(r) and r['rating'] < loss['rating']), key=lambda r: (-r['rating'], r['player_id']))[:3]
            method = 'NEXT_UP_TO_THREE_STRICTLY_LOWER_AVAILABLE'
            if not candidates:
                flags.append('replacement_pool_unresolved')
        if flags:
            results.append({'player_id': loss['player_id'], 'resolved': False, 'burden': None, 'missing_flags': flags, 'primary_replacement_ids': [r['player_id'] for r in primary], 'primary_replacement_rating': sum(r['rating'] for r in primary)/len(primary) if primary else None, 'primary_prior_resolved': bool(primary) and not actual, 'primary_burden': max(0.,loss['rating']-sum(r['rating'] for r in primary)/len(primary))*loss['workload'] if primary and not actual else None})
            continue
        chosen = [r['player_id'] for r in candidates]; used.update(chosen)
        if method == 'VERIFIED_ACTUAL':
            primary = candidates
        prior_rating = sum(r['rating'] for r in primary)/len(primary) if primary else None
        rating = sum(r['rating'] for r in candidates) / len(candidates)
        results.append({'player_id': loss['player_id'], 'resolved': True, 'replacement_ids': chosen, 'replacement_rating': rating,
                        'primary_replacement_ids': [r['player_id'] for r in primary], 'primary_replacement_rating': prior_rating,
                        'primary_prior_resolved': prior_rating is not None,
                        'primary_burden': max(0., loss['rating'] - prior_rating)*loss['workload'] if prior_rating is not None else None,
                        'method': method, 'signed_rating_gap': loss['rating'] - rating,
                        'burden': max(0., loss['rating'] - rating) * loss['workload'], 'missing_flags': [],
                        'allocation_assumption': 'exclusive full-pool reservation; not measured snaps'})
    return results


def state_relative_burden(current_burden, embedded_burden, rate=0.15, role_restoration=None):
    """Availability state parallel to score EWMA, never a modification to Elo.

    A current return needs explicit expected restoration fraction; Available alone
    does not justify a full benefit. Unknown inputs remain unknown. Caller updates
    embedded state only after a completed, observed game using that game's burden.
    """
    def nonnegative(v):
        return not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v) and v >= 0
    if not nonnegative(embedded_burden) or not nonnegative(current_burden):
        return {'incremental_burden': None, 'next_embedded_burden': None, 'missing_flags': ['burden_history_or_current_unknown']}
    if not isinstance(rate, (int, float)) or isinstance(rate, bool) or not math.isfinite(rate) or not 0 <= rate <= 1:
        raise ValueError('invalid update rate')
    current = current_burden
    if role_restoration is not None:
        if isinstance(role_restoration, bool) or not isinstance(role_restoration, (int,float)) or not math.isfinite(role_restoration) or not 0 <= role_restoration <= 1:
            raise ValueError('invalid role restoration')
        current = current_burden * (1 - role_restoration)
    return {'incremental_burden': current - embedded_burden,
            'next_embedded_burden': (1 - rate) * embedded_burden + rate * current,
            'missing_flags': [], 'scoring_points': None, 'elo_changed': False}


def build_identity_crosswalk(rows):
    """Evidence-backed ESPN/EA/team-season bijection, never a fuzzy name join."""
    seen_espn, seen_ea, seen_name = set(), set(), set()
    result = []
    for row in rows:
        required = ('espn_id', 'ea_id', 'team', 'season', 'normalized_name', 'evidence_ref')
        if any(row.get(k) in (None, '') for k in required) or row.get('identity_verified') is not True:
            raise ValueError('identity evidence required')
        scope = (row['team'], row['season'])
        keys = (scope + (str(row['espn_id']),), scope + (str(row['ea_id']),), scope + (row['normalized_name'].casefold().strip(),))
        if keys[0] in seen_espn or keys[1] in seen_ea or keys[2] in seen_name:
            raise ValueError('ambiguous or duplicated identity')
        seen_espn.add(keys[0]); seen_ea.add(keys[1]); seen_name.add(keys[2])
        result.append(dict(row))
    return result


def known_unknown_coverage(rows):
    resolved = sum(r.get('resolved') is True for r in rows)
    return {'total': len(rows), 'resolved': resolved, 'unresolved': len(rows)-resolved,
            'resolved_fraction': resolved/len(rows) if rows else None,
            'unknown_is_healthy': False, 'missing_flags': sorted({f for r in rows for f in r.get('missing_flags', [])})}


def uncertain_scenarios(active_burden, out_burden, active_probability=None):
    """Scenario burdens only; no fabricated status probability or score conversion."""
    for b in (active_burden, out_burden):
        if isinstance(b, bool) or not isinstance(b, (int,float)) or not math.isfinite(b) or b < 0:
            raise ValueError('invalid burden')
    result = {'active': active_burden, 'out': out_burden, 'expected_burden': None, 'probability_source_required': True}
    if active_probability is not None:
        raise ValueError('probability mixing requires a separately authenticated probability model')
    return result


def verified_ol_continuity(previous, current, cutoff):
    """Count verified unchanged OL slots, never infer participation or snaps."""
    slots = {'LT','LG','C','RG','RT'}
    for lineup in (previous,current):
        if lineup.get('verified') is not True or not _known_before(lineup,cutoff) or set(lineup.get('slots',{})) != slots or len(set(lineup['slots'].values())) != 5:
            return {'unchanged_slots': None, 'missing_flags': ['verified_complete_lineup_required'], 'snaps': None}
    return {'unchanged_slots': sum(previous['slots'][s] == current['slots'][s] for s in slots), 'missing_flags': [], 'snaps': None}
