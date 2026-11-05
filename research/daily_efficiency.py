"""Independent opponent-adjusted daily challengers; no official promotion."""
import math
from collections import defaultdict
import numpy as np
from scipy.sparse import lil_matrix, vstack, eye
from scipy.sparse.linalg import lsqr
from project_craps.common import instant

VERSION='daily-opponent-strength-v1'


def _finite(x):
    if isinstance(x,bool) or not math.isfinite(float(x)): raise ValueError('finite number required')
    return float(x)


def _fit(rows, teams, ridge, mode):
    index={t:i for i,t in enumerate(teams)}; n=len(teams); x=lil_matrix((2*len(rows),2*n+2)); y=[]; weights=[]
    lastseason=max(r['season'] for r in rows)
    for i,r in enumerate(rows):
        p=r.get('possessions') if mode=='box_estimated_ppp' else 1
        for k,(team,opp,score,home) in enumerate([(r['home_id'],r['away_id'],r['home_score'],True),(r['away_id'],r['home_id'],r['away_score'],False)]):
            j=2*i+k; x[j,0]=1; x[j,1+index[team]]=1; x[j,1+n+index[opp]]=-1; x[j,-1]=float(home and not r['neutral'])
            y.append(score/p); weights.append(math.sqrt(.5**(lastseason-r['season'])))
    w=np.asarray(weights); x=x.tocsr().multiply(w[:,None]); penalty=eye(2*n+2,format='lil')*math.sqrt(ridge);penalty[0,0]=0
    beta=lsqr(vstack([x,penalty.tocsr()]),np.r_[np.asarray(y)*w,np.zeros(2*n+2)],atol=1e-10,btol=1e-10)[0]
    return dict(intercept=float(beta[0]),home_effect=float(beta[-1]),offense={t:float(beta[1+i]) for t,i in index.items()},defense={t:float(beta[1+n+i]) for t,i in index.items()})


def _scores(model,event,possessions):
    h=str(event['home_id']);a=str(event['away_id']); b=model['parameters'];o=b['offense'];d=b['defense']
    if h not in o or a not in o:return None
    home=b['intercept']+o[h]-d[a]+(0 if event['neutral'] else b['home_effect']); away=b['intercept']+o[a]-d[h]
    return [max(0,home*possessions),max(0,away*possessions)]


def expected_possessions(model,event):
    """Prior box possessions only; no football count invented."""
    if model['mode']!='box_estimated_ppp': return None
    h=model['pace'].get(str(event['home_id'])); a=model['pace'].get(str(event['away_id']))
    if h is None or a is None:return None
    return (h+a)/2


def fit(rows, *, sport, cutoff, ridge=20., calibration_fraction=.2):
    """Fixed chronological 80/20 fit/calibration. No outcome-based tuning.

    Historical captures remain retrospective, not original pregame receipts.
    Rows need event_id,kickoff,season,home_id,away_id,home_score,away_score,neutral.
    NCAAB requires real box-derived estimated possessions for every fitted row.
    """
    if sport not in ('NCAAF','NFL','NCAAB'):raise ValueError('unsupported sport')
    if not 0<calibration_fraction<.5 or ridge<=0:raise ValueError('invalid fixed fit settings')
    eligible=[];seen=set(); excluded=defaultdict(int)
    for row in rows:
        if row['event_id'] in seen:raise ValueError('duplicate event')
        seen.add(row['event_id'])
        if instant(row['kickoff'])>=instant(cutoff):excluded['not_before_cutoff']+=1;continue
        if not row.get('final',False):excluded['not_final']+=1;continue
        r=dict(row);r['season']=int(r['season']);r['home_id']=str(r['home_id']);r['away_id']=str(r['away_id'])
        if type(r.get('neutral')) is not bool:raise ValueError('explicit neutral required')
        for k in ('home_score','away_score'):
            r[k]=_finite(r[k])
            if r[k]<0:raise ValueError('negative score')
        if sport=='NCAAB' and (r.get('possessions') is None or _finite(r['possessions'])<=0):excluded['box_possessions_missing']+=1;continue
        eligible.append(r)
    eligible.sort(key=lambda r:(r['kickoff'],r['event_id']))
    if len(eligible)<30:raise ValueError('at least30 historical games needed')
    boundary=eligible[int(len(eligible)*(1-calibration_fraction))]['kickoff'][:10]
    train=[r for r in eligible if r['kickoff'][:10]<boundary];cal=[r for r in eligible if r['kickoff'][:10]>=boundary]
    if not train or not cal:raise ValueError('distinct chronological train/calibration dates required')
    teams=sorted({r[k] for r in train for k in ('home_id','away_id')}); mode='box_estimated_ppp' if sport=='NCAAB' else 'full_score_opponent_adjusted_fallback'
    model={'version':VERSION,'sport':sport,'approval':'RESEARCH_ONLY','mode':mode,'cutoff':cutoff,'parameters':_fit(train,teams,ridge,mode),'ridge':ridge,'season_weight_retention':.5,'train_n':len(train),'train_last':train[-1]['kickoff'],'calibration_first':cal[0]['kickoff'],'pace':{},'residual_pairs':[],'excluded':dict(excluded),'source_authentication':'retrospective source captures; original publication unverified'}
    pace=defaultdict(list)
    for r in train:
        if r.get('possessions'):
            for t in (r['home_id'],r['away_id']):pace[t].append((r['season'],r['possessions']))
    latest=max(r['season'] for r in train)
    model['pace']={t:sum(p*(.5**(latest-s)) for s,p in vals)/sum(.5**(latest-s) for s,p in vals) for t,vals in pace.items()}
    missing=0
    for r in cal:
        p=expected_possessions(model,r) if sport=='NCAAB' else 1
        scores=_scores(model,r,p) if p is not None else None
        if scores is None:missing+=1;continue
        model['residual_pairs'].append([r['home_score']-scores[0],r['away_score']-scores[1]])
    model['calibration_n']=len(model['residual_pairs']);model['calibration_unseen_teams']=missing
    if model['calibration_n']<10:raise ValueError('insufficient residual calibration')
    model['calibration_margin_mae']=float(np.mean([abs(h-a) for h,a in model['residual_pairs']]))
    return model


def predict(model,event, *, expected_possessions_override=None):
    if instant(event['kickoff'])<=instant(model['cutoff']):raise ValueError('prediction must follow fit cutoff')
    if type(event.get('neutral')) is not bool:raise ValueError('explicit neutral required')
    p=expected_possessions_override if expected_possessions_override is not None else expected_possessions(model,event)
    if model['mode']!='box_estimated_ppp':p=1
    if p is None:return {'status':'MISSING_PRIOR_POSSESSIONS','production_approved':False}
    p=_finite(p)
    if p<=0:raise ValueError('positive expected possessions required')
    scores=_scores(model,event,p)
    if scores is None:return {'status':'UNSEEN_TEAM','production_approved':False}
    samples=[[max(0,int(round(scores[0]+h))),max(0,int(round(scores[1]+a)))] for h,a in model['residual_pairs']]
    return {'status':'RESEARCH_ONLY','mode':model['mode'],'expected_possessions':p if model['mode']=='box_estimated_ppp' else None,'point_scores':scores,'paired_score_samples':samples,'distribution_center_scores':np.mean(samples,axis=0).tolist(),'production_approved':False}


def parse_neutral(value):
    """Strict source adapter: string FALSE must not become Python bool(True)."""
    if isinstance(value,bool): return value
    if isinstance(value,str) and value.strip().upper() in ('TRUE','FALSE'):
        return value.strip().upper()=='TRUE'
    raise ValueError('unrecognized neutral venue flag')
