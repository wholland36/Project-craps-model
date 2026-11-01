"""Chronological research fit/evaluation, never automated model approval."""
import math
from collections import defaultdict
import numpy as np
from sklearn.linear_model import Ridge
from .common import code_fingerprint, digest, envelope, now, stamp
from .features import FEATURES, historical_features
from .model import VERSION, outcome_masses, predict, score_distribution


def fit_model(rows, sport, train_end, calibration_year, minimum=200):
    if train_end >= calibration_year:
        raise ValueError('training must precede calibration')
    train = [(g, x) for g, x in rows if g['season'] <= train_end]
    validation = [(g, x) for g, x in rows if g['season'] == calibration_year]
    if min(len(train), len(validation)) < minimum:
        raise ValueError('insufficient training/calibration games')
    if max(g['kickoff'] for g, _ in train) >= min(g['kickoff'] for g, _ in validation):
        raise ValueError('overlapping chronological splits')
    X = np.array([x for g, x in train])
    VX = np.array([x for g, x in validation])
    artifact = {'version': VERSION, 'sport': sport, 'approval': 'RESEARCH_ONLY',
                'features': FEATURES, 'alpha': 1000 if sport == 'NFL' else 1500,
                'train_end_season': train_end, 'calibration_season': calibration_year,
                'train_n': len(train), 'calibration_n': len(validation),
                'train_last_kickoff': max(g['kickoff'] for g, _ in train),
                'calibration_last_kickoff': max(g['kickoff'] for g, _ in validation),
                'train_home_rate': sum(g['home_score'] > g['away_score'] for g, _ in train) / len(train),
                'distribution_assumption': 'paired validation residuals; round feasible nonnegative integer scores; FBS condition on non-tie',
                'uncertainty': 'NOT_VALIDATED; empirical support is not an uncertainty interval',
                'historical_point_in_time_verified': False}
    residuals = []
    for name, function in [('margin', lambda g: g['home_score'] - g['away_score']),
                           ('total', lambda g: g['home_score'] + g['away_score'])]:
        model = Ridge(alpha=artifact['alpha']).fit(X, [function(g) for g, _ in train])
        artifact[name] = {'coefficients': model.coef_.tolist(), 'intercept': float(model.intercept_)}
        residuals.append(np.array([function(g) for g, _ in validation]) - model.predict(VX))
    artifact['residual_pairs'] = np.column_stack(residuals).tolist()
    return artifact


def binary_metrics(probabilities, targets):
    p, y = np.array(probabilities), np.array(targets)
    clipped = np.clip(p, 1e-9, 1 - 1e-9)
    return {'n': len(y), 'brier': float(np.mean((p - y) ** 2)),
            'logloss': float(-np.mean(y * np.log(clipped) + (1 - y) * np.log(1 - clipped)))}


def evaluate(artifact, rows):
    if not rows:
        raise ValueError('no holdout games')
    if min(g['kickoff'] for g, _ in rows) <= artifact['calibration_last_kickoff']:
        raise ValueError('holdout overlaps calibration')
    p, y, elo, margin_errors, total_errors, groups = [], [], [], [], [], []
    # Synthetic thresholds were fixed before fitting this version; no odds-derived ROI.
    thresholds = [('spread', 'home', -3.0), ('spread', 'home', -3.5),
                  ('total', 'over', 45.0), ('total', 'over', 45.5)]
    diagnostics = {str(t): {'masses': [], 'truth': []} for t in thresholds}
    for g, x in rows:
        scores = score_distribution(artifact, x)
        p.append(outcome_masses(scores, 'moneyline', 'home', tie_policy='refund')[0])
        y.append(int(g['home_score'] > g['away_score']))
        elo.append(1 / (1 + 10 ** (-x[4] / 400)))
        pm, pt = predict(artifact, x)
        margin_errors.append(abs(g['home_score'] - g['away_score'] - pm))
        total_errors.append(abs(g['home_score'] + g['away_score'] - pt))
        groups.append(g['kickoff'][:4] + '-' + str(__import__('datetime').date.fromisoformat(g['kickoff'][:10]).isocalendar()[1]))
        for market, selection, line in thresholds:
            key = str((market, selection, line))
            masses = outcome_masses(scores, market, selection, line)
            actual = outcome_masses([(g['home_score'], g['away_score'])], market, selection, line)
            diagnostics[key]['masses'].append(masses)
            diagnostics[key]['truth'].append(actual)
    report = {'home_win_binary_definition': 'home score > away score; ties are false; ticket push mass evaluated separately',
              'homewin': binary_metrics(p, y),
              'home_rate_baseline': binary_metrics([artifact['train_home_rate']] * len(y), y),
              'market_blind_elo_baseline': binary_metrics(elo, y),
              'margin_mae': float(np.mean(margin_errors)), 'total_mae': float(np.mean(total_errors)),
              'calibration_buckets': [], 'synthetic_thresholds': {}}
    for lo in np.arange(0, 1, .2):
        indices = [i for i, v in enumerate(p) if lo <= v < lo + .2 + (1e-12 if lo > .7 else 0)]
        if indices:
            report['calibration_buckets'].append({'lower': float(lo), 'n': len(indices),
                'mean_p': float(np.mean([p[i] for i in indices])),
                'observed': float(np.mean([y[i] for i in indices]))})
    for key, values in diagnostics.items():
        m, t = np.array(values['masses']), np.array(values['truth'])
        eligible = (t[:, 1] == 0) & ((m[:, 0] + m[:, 2]) > 0)
        report['synthetic_thresholds'][key] = {'n': len(m), 'actual_pushes': int(t[:, 1].sum()),
            'mean_predicted_push': float(m[:, 1].mean()),
            'threeway_brier': float(np.mean(np.sum((m - t) ** 2, axis=1))),
            'threeway_logloss': float(-np.mean(np.sum(t * np.log(np.clip(m, 1e-9, 1)), axis=1))),
            'conditional_nonpush': binary_metrics(m[eligible, 0] / (1 - m[eligible, 1]), t[eligible, 0]) if eligible.any() else None}
    # Paired week-cluster bootstrap versus independent Elo, descriptive only.
    delta = (np.array(p) - y) ** 2 - (np.array(elo) - y) ** 2
    blocks = defaultdict(list)
    for i, group in enumerate(groups):
        blocks[group].append(i)
    chunks = [np.array(v) for v in blocks.values()]
    rng = np.random.default_rng(1907)
    differences = [float(delta[np.concatenate([chunks[i] for i in rng.integers(0, len(chunks), len(chunks))])].mean()) for _ in range(1000)]
    report['model_minus_elo_brier'] = {'difference': float(delta.mean()),
        'week_cluster_bootstrap_95': np.quantile(differences, [.025, .975]).tolist(),
        'replicates': 1000, 'interpretation': 'descriptive; not a promotion or profitability test'}
    report['bookmaker_benchmark'] = 'NOT_COMPUTED: original book IDs and publication timestamps unavailable'
    report['roi_clv_drawdown'] = 'NOT_COMPUTED: no authenticated executable quote history'
    return report


def train(snapshot_wrapper, test_year=2025, folds=(2022, 2023, 2024, 2025), minimum=200):
    snapshot = snapshot_wrapper['payload']
    sport = snapshot['sport']
    # Future seasons cannot affect feature construction, fitting or held-out evaluation.
    games = [g for g in snapshot['games'] if g['season'] <= test_year]
    rows, state = historical_features(games)
    artifact = fit_model(rows, sport, test_year - 2, test_year - 1, minimum)
    artifact.update({'built_at': stamp(now()), 'implementation_sha256': code_fingerprint(), 'source_snapshot_sha256': snapshot_wrapper['sha256'],
                     'source_manifest': snapshot['sources'], 'state': state,
                     'state_through': max(g['kickoff'] for g, _ in rows),
                     'history_start_season': min(g['season'] for g, _ in rows),
                     'feature_code_version': 'rolling-score-elo-rest-neutral-v1'})
    report = {'sport': sport, 'status': 'RESEARCH_ONLY', 'folds': [],
              'historical_point_in_time_verified': False, 'new_version': VERSION,
              'warning': 'New challenger; no probability calibration or wagering approval is claimed.'}
    for year in folds:
        fold_model = fit_model(rows, sport, year - 2, year - 1, minimum)
        test_rows = [(g, x) for g, x in rows if g['season'] == year]
        report['folds'].append({'test_season': year, 'train_n': fold_model['train_n'],
                               'calibration_n': fold_model['calibration_n'], **evaluate(fold_model, test_rows)})
    return envelope(artifact), report
