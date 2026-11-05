"""User-specified non-QB replacement prior; never a scoring-point valuation."""
from statistics import mean


def replacement_prior(injured, roster, unavailable_ids=(), verified_replacement=None):
    if injured['position_group'] == 'QB':
        raise ValueError('QB requires separate verified replacement analysis')
    ids = [str(p['ea_player_id']) for p in roster]
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate player IDs')
    for p in [injured] + list(roster):
        if type(p['overall_rating']) is not int or not 0 <= p['overall_rating'] <= 99:
            raise ValueError('invalid overall rating')
    unavailable = set(map(str, unavailable_ids)) | {str(injured['ea_player_id'])}
    eligible = [p for p in roster if p['ea_team_id'] == injured['ea_team_id']
                and p['position_group'] == injured['position_group']
                and p['iteration'] == injured['iteration']
                and str(p['ea_player_id']) not in unavailable]
    if verified_replacement is not None:
        candidates = [p for p in eligible if str(p['ea_player_id']) == str(verified_replacement)]
        if len(candidates) != 1:
            raise ValueError('verified replacement unavailable or incompatible')
        selected = candidates
        method = 'VERIFIED_REPLACEMENT'
    else:
        candidates = [p for p in eligible if p['overall_rating'] < injured['overall_rating']]
        selected = sorted(candidates, key=lambda p: (-p['overall_rating'], str(p['ea_player_id'])))[:3]
        method = 'NEXT_THREE_LOWER_SAME_TEAM_POSITION_PROXY'
        if not selected:
            return {'status': 'INCOMPLETE', 'reason': 'no lower-rated eligible teammates',
                    'available_candidates': len(selected), 'replacement_rating': None, 'rating_gap': None}
    rating = mean(p['overall_rating'] for p in selected)
    return {'status': 'RESEARCH_PRIOR_ONLY', 'method': method,
            'injured_id': str(injured['ea_player_id']), 'position': injured['position_group'],
            'replacement_ids': [str(p['ea_player_id']) for p in selected],
            'replacement_rating': rating, 'replacement_count': len(selected), 'rating_gap': injured['overall_rating'] - rating,
            'nonnegative_rating_loss': max(0, injured['overall_rating'] - rating),
            'lost_snap_share': None, 'scoring_point_adjustment': None,
            'production_approved': False}
