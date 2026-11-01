import json
from pathlib import Path
import numpy as np
from project_craps.common import bytes_hash,digest,envelope,now,stamp,unwrap

PROTOCOL=json.loads((Path(__file__).parent/'protocol.json').read_text())


def fingerprint():
    return digest({p.name:bytes_hash(p.read_bytes()) for p in sorted(Path(__file__).parent.glob('*.py'))}|{'protocol':digest(PROTOCOL)})


def category(margin):
    absolute=np.abs(margin)
    output=np.zeros(absolute.shape,dtype=int)
    for i,(lo,hi) in enumerate(PROTOCOL['absolute_margin_bins']):
        mask=(absolute>=lo)&((absolute<=hi) if hi is not None else True)
        output[mask]=i
    return output


def support(parent,mu):
    residuals=np.array(parent['residual_pairs'])
    shifted=residuals+np.array(mu)
    h=np.maximum(0,np.floor((shifted[:,1]+shifted[:,0])/2+.5))
    a=np.maximum(0,np.floor((shifted[:,1]-shifted[:,0])/2+.5))
    return np.column_stack([h,a])


def fit(parent_wrapper,minimum=200):
    parent=unwrap(parent_wrapper)
    if parent['variant']!='efficiency' or parent['approval']!='RESEARCH_ONLY':raise ValueError('fixed efficiency parent required')
    actual=np.array(parent['validation_scores']);residual=np.array(parent['residual_pairs']);n=len(actual)
    if n<minimum or len(residual)!=n:raise ValueError('insufficient aligned calibration data')
    mu=np.column_stack([actual[:,0]-actual[:,1],actual.sum(axis=1)])-residual
    # Each row's distribution excludes its own residual, avoiding an automatic exact actual-score draw.
    categories=np.empty((n,n),dtype=np.int8);eligible=~np.eye(n,dtype=bool)
    for i in range(n):
        scores=support(parent,mu[i]);categories[i]=category(scores[:,0]-scores[:,1])
        if parent['sport']=='NCAAF':eligible[i]&=scores[:,0]!=scores[:,1]
    if np.any(eligible.sum(axis=1)==0):raise ValueError('empty leave-one-out support')
    counts=np.stack([((categories==k)&eligible).sum(axis=1) for k in range(8)],axis=1).astype(float)
    base=(counts/counts.sum(axis=1,keepdims=True)).mean(axis=0)
    truth=np.bincount(category(actual[:,0]-actual[:,1]),minlength=8)/n
    strength=PROTOCOL['prior_strength_games'];target=(n*truth+strength*base)/(n+strength)
    theta=np.ones(8);error=None
    for iteration in range(PROTOCOL['maximum_iterations']):
        mass=counts*theta;pred=(mass/mass.sum(axis=1,keepdims=True)).mean(axis=0)
        error=float(np.max(np.abs(pred-target)))
        if error<PROTOCOL['convergence_tolerance']:break
        ratio=np.divide(target,pred,out=np.ones(8),where=pred>0)
        theta*=ratio**PROTOCOL['learning_rate']
        theta=np.clip(theta,*PROTOCOL['weight_clip']);theta/=np.exp(np.mean(np.log(theta)))
    mass=counts*theta;pred=(mass/mass.sum(axis=1,keepdims=True)).mean(axis=0)
    error=float(np.max(np.abs(pred-target)))
    return envelope({'version':'football-key-margin-calibration-v2-research','sport':parent['sport'],
        'parent_sha256':parent_wrapper['sha256'],'parent_variant':'efficiency','theta':theta.tolist(),
        'calibration_n':n,'calibration_season':parent['calibration_season'],
        'calibration_last_kickoff':parent['calibration_last_kickoff'],
        'protocol_sha256':digest(PROTOCOL),'implementation_sha256':fingerprint(),'built_at':stamp(now()),
        'base_margin_category_mass':base.tolist(),'observed_margin_category_mass':truth.tolist(),
        'shrunk_target_mass':target.tolist(),'fitted_margin_category_mass':pred.tolist(),
        'max_calibration_error':error,'iterations':iteration+1,'leave_one_out_residuals':True,
        'approval':'RESEARCH_ONLY','approved_risk':0})


def distribution(parent_wrapper,calibrator_wrapper,mu):
    parent=unwrap(parent_wrapper);calibrator=unwrap(calibrator_wrapper)
    if calibrator['parent_sha256']!=parent_wrapper['sha256'] or calibrator['implementation_sha256']!=fingerprint():
        raise ValueError('lattice parent/code mismatch')
    scores=support(parent,mu);cats=category(scores[:,0]-scores[:,1]);weights=np.array(calibrator['theta'])[cats]
    if parent['sport']=='NCAAF':
        keep=scores[:,0]!=scores[:,1];scores,weights=scores[keep],weights[keep]
    if not len(scores) or not np.all(np.isfinite(weights)) or np.any(weights<=0):raise ValueError('invalid corrected distribution')
    return scores,weights/weights.sum()
