"""Registered ablations, paired rolling-origin comparison and failure analysis."""
import json
from pathlib import Path
from collections import defaultdict
from datetime import date
import numpy as np
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from project_craps.common import bytes_hash, create, digest, envelope, now, stamp
from project_craps.model import outcome_masses
from project_craps.train import binary_metrics
from .features import feature_names

PROTOCOL = json.loads((Path(__file__).parent/'protocol.json').read_text())
VARIANTS = PROTOCOL['variants']


def fingerprint():
    root=Path(__file__).parent
    return digest({p.name:bytes_hash(p.read_bytes()) for p in sorted(root.glob('*.py'))}|{'protocol':digest(PROTOCOL)})


def fit(rows,variant,test_year,minimum=200):
    tr=[r for r in rows if r['game']['season']<=test_year-2]
    ca=[r for r in rows if r['game']['season']==test_year-1]
    if min(len(tr),len(ca))<minimum:
        raise ValueError('insufficient fit/calibration cohort')
    if max(r['game']['kickoff'] for r in tr)>=min(r['game']['kickoff'] for r in ca):
        raise ValueError('chronological split overlap')
    sport=tr[0]['game']['sport']
    X=np.array([r['features'][variant] for r in tr]);CX=np.array([r['features'][variant] for r in ca])
    if variant=='original':
        center=np.zeros(X.shape[1]);scale=np.ones(X.shape[1]);alpha=1000 if sport=='NFL' else 1500
    else:
        scaler=StandardScaler().fit(X);center=scaler.mean_;scale=scaler.scale_;alpha=PROTOCOL['scaled_ridge_alpha']
    result={'variant':variant,'sport':sport,'features':feature_names(variant),'alpha':alpha,
            'center':center.tolist(),'scale':scale.tolist(),'train_n':len(tr),'calibration_n':len(ca),
            'train_end_season':test_year-2,'calibration_season':test_year-1,
            'train_last_kickoff':max(r['game']['kickoff'] for r in tr),
            'calibration_last_kickoff':max(r['game']['kickoff'] for r in ca),
            'approval':'RESEARCH_ONLY','historical_point_in_time_verified':False}
    residuals=[]
    for target,fn in [('margin',lambda g:g['home_score']-g['away_score']),('total',lambda g:g['home_score']+g['away_score'])]:
        model=Ridge(alpha=alpha).fit((X-center)/scale,[fn(r['game']) for r in tr])
        result[target]={'coefficients':model.coef_.tolist(),'intercept':float(model.intercept_)}
        residuals.append(np.array([fn(r['game']) for r in ca])-model.predict((CX-center)/scale))
    result['residual_pairs']=np.column_stack(residuals).tolist()
    result['validation_scores']=[[r['game']['home_score'],r['game']['away_score']] for r in ca]
    return result


def means(model,features):
    x=(np.array(features)-model['center'])/model['scale']
    return np.array([model[k]['intercept']+np.dot(model[k]['coefficients'],x) for k in ['margin','total']])


def distribution(model,features):
    mu=means(model,features)
    pairs=np.array(model['residual_pairs'])+mu
    home=np.maximum(0,np.floor((pairs[:,1]+pairs[:,0])/2+.5))
    away=np.maximum(0,np.floor((pairs[:,1]-pairs[:,0])/2+.5))
    scores=np.column_stack([home,away]);weights=np.full(len(scores),1/len(scores))
    if model['variant']=='score_kernel':
        analogs=np.array(model['validation_scores'])
        am,at=analogs[:,0]-analogs[:,1],analogs.sum(axis=1)
        kernel=np.exp(-.5*((am-mu[0])/PROTOCOL['kernel_margin_bandwidth'])**2-.5*((at-mu[1])/PROTOCOL['kernel_total_bandwidth'])**2)
        kernel=np.maximum(kernel,1e-12);kernel/=kernel.sum()
        fraction=PROTOCOL['kernel_fraction']
        scores=np.vstack([scores,analogs]);weights=np.concatenate([(1-fraction)*weights,fraction*kernel])
    if model['sport']=='NCAAF':
        keep=scores[:,0]!=scores[:,1];scores,weights=scores[keep],weights[keep]
    if not len(scores):raise ValueError('empty discrete distribution')
    weights=weights/weights.sum()
    return scores,weights


def masses(scores,weights,market,line=0):
    values=(scores[:,0]-scores[:,1]+line) if market=='spread' else scores.sum(axis=1)-line
    return np.array([weights[values>0].sum(),weights[values==0].sum(),weights[values<0].sum()])


def predict_records(model,rows):
    output=[]
    for row in rows:
        g=row['game'];x=row['features'][model['variant']]
        scores,w=distribution(model,x);mu=means(model,x)
        margin=g['home_score']-g['away_score'];total=g['home_score']+g['away_score']
        thresholds={}
        for market,lines in [('spread',PROTOCOL['synthetic_home_handicaps']),('total',PROTOCOL['synthetic_total_lines'])]:
            for line in lines:
                p=masses(scores,w,market,line)
                actual=margin+line if market=='spread' else total-line
                t=[int(actual>0),int(actual==0),int(actual<0)]
                thresholds[market+':'+str(line)]={'p':p.tolist(),'truth':t}
        iso=date.fromisoformat(g['kickoff'][:10]).isocalendar()
        output.append({'event_id':g['event_id'],'sport':g['sport'],'season':g['season'],
            'kickoff':g['kickoff'],'cluster':str(iso[0])+'-'+str(iso[1]),'variant':model['variant'],
            'p_home_win':float(masses(scores,w,'spread',0)[0]),'actual_home_win':int(margin>0),
            'actual_margin':margin,'actual_total':total,'pred_margin':float(mu[0]),'pred_total':float(mu[1]),
            'margin_mae':abs(float(mu[0])-margin),'total_mae':abs(float(mu[1])-total),
            'pred_abs_margin_3':float(w[np.abs(scores[:,0]-scores[:,1])==3].sum()),
            'pred_abs_margin_7':float(w[np.abs(scores[:,0]-scores[:,1])==7].sum()),
            'pred_total_60plus':float(w[scores.sum(axis=1)>=60].sum()),
            'pred_tie':float(w[scores[:,0]==scores[:,1]].sum()),
            'actual_overtime':row['metadata'].get('overtime'),
            'efficiency_complete':row['efficiency_complete'],'metadata':row['metadata'],
            'thresholds':thresholds})
    return output


def metrics(records):
    if not records:return None
    base=binary_metrics([r['p_home_win'] for r in records],[r['actual_home_win'] for r in records])
    base.update(margin_mae=float(np.mean([r['margin_mae'] for r in records])),
                total_mae=float(np.mean([r['total_mae'] for r in records])),
                complete_efficiency_n=sum(r['efficiency_complete'] for r in records))
    base['event_rates']={key:{'predicted':float(np.mean([r['pred_'+key] for r in records])),
        'observed':float(np.mean([abs(r['actual_margin'])==int(key[-1]) if key.startswith('abs_margin') else (r['actual_total']>=60 if key=='total_60plus' else r['actual_margin']==0) for r in records]))}
        for key in ('abs_margin_3','abs_margin_7','total_60plus','tie')}
    base['thresholds']={}
    for key in records[0]['thresholds']:
        p=np.array([r['thresholds'][key]['p'] for r in records]);t=np.array([r['thresholds'][key]['truth'] for r in records])
        eligible=(t[:,1]==0)&((p[:,0]+p[:,2])>0)
        base['thresholds'][key]={'n':len(p),'pushes':int(t[:,1].sum()),'predicted_push':float(p[:,1].mean()),
            'threeway_brier':float(((p-t)**2).sum(axis=1).mean()),
            'threeway_logloss':float(-(t*np.log(np.maximum(p,1e-9))).sum(axis=1).mean()),
            'nonpush':binary_metrics(p[eligible,0]/(1-p[eligible,1]),t[eligible,0]) if eligible.any() else None}
    return base


def groups(records):
    output={}
    # Model buckets are explicitly separate from bookmaker buckets.
    functions={'model_favorite':lambda r:'home' if r['pred_margin']>=0 else 'away',
      'model_margin_size':lambda r:'0-3' if abs(r['pred_margin'])<=3 else '3-7' if abs(r['pred_margin'])<=7 else '7+',
      'model_total':lambda r:'below40' if r['pred_total']<40 else '40-50' if r['pred_total']<=50 else 'above50',
      'confidence':lambda r:str(int(max(r['p_home_win'],1-r['p_home_win'])*10)/10),
      'book_favorite_unverified':lambda r:'UNKNOWN' if r['metadata'].get('spread_home_margin') is None else 'home' if r['metadata']['spread_home_margin']>=0 else 'away',
      'book_spread_size_unverified':lambda r:'UNKNOWN' if r['metadata'].get('spread_home_margin') is None else '0-3' if abs(r['metadata']['spread_home_margin'])<=3 else '3-7' if abs(r['metadata']['spread_home_margin'])<=7 else '7+',
      'book_total_unverified':lambda r:'UNKNOWN' if r['metadata'].get('total_line') is None else 'below40' if r['metadata']['total_line']<40 else '40-50' if r['metadata']['total_line']<=50 else 'above50',
      'overtime_diagnostic':lambda r:'UNKNOWN' if r['actual_overtime'] is None else 'OT' if r['actual_overtime'] else 'REGULATION'}
    for name,fn in functions.items():
        bins=defaultdict(list)
        for record in records:bins[fn(record)].append(record)
        output[name]={key:metrics(values) for key,values in bins.items()}
    return output


def compare(baseline,challenger):
    by_id={r['event_id']:r for r in baseline}
    if set(by_id)!={r['event_id'] for r in challenger}:raise ValueError('paired cohort mismatch')
    delta=[];blocks=defaultdict(list)
    for i,r in enumerate(challenger):
        b=by_id[r['event_id']];y=r['actual_home_win']
        if b['actual_home_win']!=y:raise ValueError('target mismatch')
        delta.append((r['p_home_win']-y)**2-(b['p_home_win']-y)**2);blocks[r['cluster']].append(i)
    values=np.array(delta);chunks=[np.array(v) for v in blocks.values()];rng=np.random.default_rng(PROTOCOL['bootstrap']['seed'])
    boots=[values[np.concatenate([chunks[i] for i in rng.integers(0,len(chunks),len(chunks))])].mean() for _ in range(PROTOCOL['bootstrap']['paired_replicates'])]
    return {'n':len(values),'challenger_minus_baseline_brier':float(values.mean()),
            'week_cluster_bootstrap_95':np.quantile(boots,[.025,.975]).tolist(),
            'multiplicity_adjusted':False,'interpretation':'descriptive already-examined retrospective data; no model promotion'}


def run(rows,output,protocol_receipt,source_hashes,minimum=200):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    report={'protocol':PROTOCOL,'protocol_registration':protocol_receipt,'source_hashes':source_hashes,
            'sport':rows[0]['game']['sport'],'folds':[],'approval':'RESEARCH_ONLY','auto_promotion':False}
    combined={v:[] for v in VARIANTS}
    for year in PROTOCOL['evaluation_seasons']:
        test=[r for r in rows if r['game']['season']==year]
        fold={'season':year,'variants':{},'paired_comparisons':{}}
        for variant in VARIANTS:
            model=fit(rows,variant,year,minimum)
            predictions=predict_records(model,test);combined[variant]+=predictions
            fold['variants'][variant]=metrics(predictions)
            create(output/(str(year)+'-'+variant+'-predictions.json'),predictions)
            model.update(built_at=stamp(now()),implementation_sha256=fingerprint(),source_hashes=source_hashes,
                         protocol_sha256=digest(PROTOCOL),version='football-efficiency-challenger-v1',
                         history_start_season=min(r['game']['season'] for r in rows))
            create(output/'fold_models'/(str(year)+'-'+variant+'.json'),envelope(model))
            if year==max(PROTOCOL['evaluation_seasons']):
                create(output/(variant+'-model.json'),envelope(model))
        for variant in VARIANTS[1:]:
            a=[r for r in combined['original'] if r['season']==year];b=[r for r in combined[variant] if r['season']==year]
            fold['paired_comparisons'][variant]=compare(a,b)
        report['folds'].append(fold)
    report['pooled']={v:{'metrics':metrics(p),'failure_groups':groups(p),
        'paired_vs_original':compare(combined['original'],p) if v!='original' else None} for v,p in combined.items()}
    report['release_gates']={'independent_future_test':'NOT_YET_AVAILABLE','historical_publication_times':'UNVERIFIED',
      'book_prices_clv_roi':'NOT_COMPUTED','calibration_uncertainty':'RESEARCH_ONLY','annual_roster_covariates':'ARCHIVED_NOT_USED'}
    create(output/'report.json',report)
    return report
