"""Frozen market-blind linear score model and discrete paired-residual support."""
import math
from .common import code_fingerprint, finite, unwrap
from .features import FEATURES

VERSION = 'football-paired-residual-v1-research'


def validate_artifact(wrapper, sport):
    artifact = unwrap(wrapper)
    if artifact.get('implementation_sha256') != code_fingerprint():
        raise ValueError('frozen inference code fingerprint changed; rebuild challenger explicitly')
    if artifact['version'] != VERSION or artifact['sport'] != sport:
        raise ValueError('model version/sport mismatch')
    if artifact['features'] != FEATURES or artifact['approval'] != 'RESEARCH_ONLY':
        raise ValueError('invalid feature order or release status')
    for name in ('margin', 'total'):
        fit = artifact[name]
        if len(fit['coefficients']) != len(FEATURES):
            raise ValueError('invalid coefficient count')
        for number in [fit['intercept']] + fit['coefficients']:
            finite(number)
    if len(artifact['residual_pairs']) < 2:
        raise ValueError('residual distribution unavailable')
    for pair in artifact['residual_pairs']:
        if len(pair) != 2:
            raise ValueError('invalid residual pair')
        for value in pair:
            finite(value)
    return artifact


def predict(artifact, features):
    if len(features) != len(FEATURES):
        raise ValueError('invalid features')
    for value in features:
        finite(value)
    means = []
    for name in ('margin', 'total'):
        fit = artifact[name]
        means.append(fit['intercept'] + sum(c * x for c, x in zip(fit['coefficients'], features)))
    return means


def score_distribution(artifact, features):
    margin, total = predict(artifact, features)
    scores = []
    for residual_margin, residual_total in artifact['residual_pairs']:
        m, t = margin + residual_margin, total + residual_total
        # Explicit research assumption: paired residual draw, then integer feasible scores.
        home = max(0, math.floor((t + m) / 2 + .5))
        away = max(0, math.floor((t - m) / 2 + .5))
        # FBS full-game including overtime cannot finish tied.
        if artifact['sport'] == 'NCAAF' and home == away:
            continue
        scores.append((home, away))
    if not scores:
        raise ValueError('empty score support')
    return scores


def outcome_masses(scores, market, selection, line=None, tie_policy=None):
    if not scores:
        raise ValueError('empty score support')
    if market == 'moneyline':
        if selection not in ('home', 'away') or tie_policy != 'refund' or line is not None:
            raise ValueError('moneyline requires home/away, null line and explicit tie refund')
        values = [(h - a) * (1 if selection == 'home' else -1) for h, a in scores]
    elif market == 'spread':
        if selection not in ('home', 'away'):
            raise ValueError('spread selection must be home/away')
        finite(line)
        if line * 2 != int(line * 2):
            raise ValueError('only integer and half-point lines supported')
        # line is the selected team's handicap, e.g. home -3 or away +3.
        values = [(h - a) * (1 if selection == 'home' else -1) + line for h, a in scores]
    elif market == 'total':
        if selection not in ('over', 'under'):
            raise ValueError('total selection must be over/under')
        finite(line)
        if line <= 0 or line * 2 != int(line * 2):
            raise ValueError('positive integer or half-point total required')
        values = [(h + a - line) * (1 if selection == 'over' else -1) for h, a in scores]
    else:
        raise ValueError('unsupported market')
    n = len(values)
    return tuple(sum(test(x) for x in values) / n for test in
                 (lambda x: x > 0, lambda x: x == 0, lambda x: x < 0))
