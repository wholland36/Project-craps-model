"""Research-only probability arithmetic. No model fitting or staking approval.

Inputs must be a discrete distribution on integer scores/margins. Constructing
that distribution and validating calibration are separate release requirements.
"""
import math


def distribution_probabilities(outcomes, weights, threshold):
    """Return unconditional (above, equal, below) masses at an exact line."""
    outcomes, weights = list(outcomes), list(weights)
    if not outcomes or len(outcomes) != len(weights):
        raise ValueError('nonempty aligned outcomes and weights required')
    if not math.isfinite(threshold):
        raise ValueError('finite threshold required')
    if any(not math.isfinite(x) or int(x) != x for x in outcomes):
        raise ValueError('integer score or margin support required')
    if any(not math.isfinite(w) or w < 0 for w in weights):
        raise ValueError('finite nonnegative weights required')
    if not math.isclose(sum(weights), 1, abs_tol=1e-12, rel_tol=0):
        raise ValueError('probability mass must sum to one')
    return tuple(sum(w for x, w in zip(outcomes, weights) if compare(x, threshold))
                 for compare in (lambda x, y: x > y, lambda x, y: x == y,
                                 lambda x, y: x < y))


def price_metrics(win, push, loss, american_odds):
    """EV per unit risk, fair American odds and conditional break-even.

    Assumes pushes refund the stake. Tie rules must be explicit upstream for
    moneylines. Returns no approval or recommended stake.
    """
    masses = (win, push, loss)
    if any(not math.isfinite(p) or p < 0 or p > 1 for p in masses):
        raise ValueError('invalid probability')
    if not math.isclose(sum(masses), 1, abs_tol=1e-12, rel_tol=0):
        raise ValueError('W/P/L must sum to one')
    if not math.isfinite(american_odds) or abs(american_odds) < 100:
        raise ValueError('American odds must be <= -100 or >= +100')
    profit = american_odds / 100 if american_odds > 0 else 100 / -american_odds
    nonpush = win + loss
    fair = None
    if win > 0 and loss > 0:
        fair = 100 * loss / win if win <= loss else -100 * win / loss
    return {'ev_per_unit_risk': win * profit - loss,
            'win_conditional_nonpush': win / nonpush if nonpush else None,
            'break_even_conditional_nonpush': 1 / (1 + profit),
            'fair_american_odds': fair,
            'approved_risk': 0, 'status': 'RESEARCH ONLY'}
