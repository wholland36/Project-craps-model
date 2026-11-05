"""Additive research governance; source byte checks never authenticate source truth."""
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from statistics import NormalDist
from urllib.parse import urlsplit


def instant(value):
    dt=datetime.fromisoformat(str(value).replace('Z','+00:00'))
    if dt.tzinfo is None: raise ValueError('timezone required')
    return dt.astimezone(timezone.utc)


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def sha(value): return hashlib.sha256(value).hexdigest()


def capture_source(url,directory,*,timeout=30):
    """Public HTTPS capture with honest local clock, no retries. Bodies remain private."""
    import requests
    p=urlsplit(url)
    if p.scheme!='https' or not p.hostname or p.username or p.password or p.query:
        raise ValueError('public HTTPS URL without credentials/query required')
    response=requests.get(url,timeout=timeout);response.raise_for_status()
    observed=datetime.now(timezone.utc).isoformat();digest=sha(response.content)
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    body=directory/(digest+'.source')
    if body.exists():
        if body.read_bytes()!=response.content: raise ValueError('source collision')
    else:
        with body.open('xb') as f:f.write(response.content)
        body.chmod(0o600)
    receipt=dict(url=url,final_url=response.url,observed_at=observed,sha256=digest,bytes=len(response.content),body_path=str(body.resolve()),published_at=None,independent_authentication=None,http_last_modified=response.headers.get('Last-Modified'),content_type=response.headers.get('Content-Type'))
    path=directory/(sha(canonical(receipt))+'.receipt.json')
    with path.open('xb') as f:f.write(canonical(receipt))
    path.chmod(0o600)
    return receipt


def source_gate(receipt,cutoff,*,require_independent=False):
    failures=[]
    try:
        if instant(receipt['observed_at'])>instant(cutoff):failures.append('observed_after_cutoff')
        if receipt.get('published_at') is None:failures.append('original_publication_unverified')
        elif instant(receipt['published_at'])>instant(receipt['observed_at']):failures.append('publication_after_observation')
        if sha(Path(receipt['body_path']).read_bytes())!=receipt['sha256']:failures.append('source_hash_mismatch')
    except (ValueError,KeyError,OSError,TypeError):failures.append('invalid_source_receipt')
    if require_independent:failures.append('independent_authentication_review_required')
    return dict(byte_and_time_checks_pass=not failures,failures=failures,independently_authenticated=False)


def append_record(directory,identity,record):
    """Create-only research records, separate from official registry."""
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    key=sha(canonical(identity));payload=dict(identity=identity,record=record,status='RESEARCH_ONLY')
    wrapper=dict(payload=payload,sha256=sha(canonical(payload)))
    with (directory/(key+'.json')).open('xb') as f:f.write(canonical(wrapper))
    return key


def planning_sample_size(*,minimum_effect,paired_sd,design_effect,alpha=.05,power=.8,hypotheses=1):
    """Normal planning approximation, not proof of power for a team/week network."""
    if any(not math.isfinite(x) for x in (minimum_effect,paired_sd,design_effect,alpha,power)) or minimum_effect<=0 or paired_sd<=0 or design_effect<1:raise ValueError('invalid planning inputs')
    if not 0<alpha<1 or not .5<power<1 or type(hypotheses)!=int or hypotheses<1:raise ValueError('invalid planning inputs')
    z=NormalDist().inv_cdf(1-alpha/(2*hypotheses))+NormalDist().inv_cdf(power)
    return dict(approximate_exposed_pairs=math.ceil(design_effect*(z*paired_sd/minimum_effect)**2),assumptions='Normal paired losses, specified design effect, Bonferroni family adjustment',actual_cluster_power_verified=False,approval=False)


def production_gate(evidence):
    required=('source_authentication','untouched_prospective','identified_position_exposures','powered_dependence_design','proper_score_improvement','push_calibration','market_relative_improvement','executable_price_evidence','fixed_policy_net_returns')
    missing=[k for k in required if evidence.get(k) is not True]
    return dict(status='RESEARCH_ONLY',unmet_requirements=missing,research_readiness_checks_pass=not missing,automatic_promotion=False)
