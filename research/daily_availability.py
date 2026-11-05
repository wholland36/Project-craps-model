"""Daily research source capture and known-input injury adapter, never official promotion."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import math
import urllib.request

SPORT_PATHS={'NCAAF':'football/college-football','NFL':'football/nfl','NCAAB':'basketball/mens-college-basketball'}
NCAAF_FROZEN_SHA='96c775fe6d6cec882e7a731ffaf71cce84340c9c4ec2fcfb5eec27aa43951e1e'
NCAAF_FROZEN_PATH=Path('/Users/wadeholland/Documents/Codex/Project-Craps/state/research-extensions/injury-shock-v1-20261105/candidate-frozen.json')


def instant(s):
    d=datetime.fromisoformat(s.replace('Z','+00:00'))
    if d.tzinfo is None:raise ValueError('timezone required')
    return d


def finite(v):return not isinstance(v,bool) and isinstance(v,(int,float)) and math.isfinite(v)


def validate_contributions(rows,sport,event,cutoff,sources):
    """Inbox records require exact IDs, proven report identity and source-bound role data."""
    known=[];unknown=[];seen=set();cut=instant(cutoff)
    identities=[(r.get('side'),r.get('player_id')) for r in rows]
    duplicates={x for x in identities if identities.count(x)>1}
    source_by_hash={s.get('sha256'):s for s in sources if s.get('status')=='CAPTURED'}
    for row in rows:
        flags=[];pid=row.get('player_id');side=row.get('side')
        identity=(side,pid)
        if identity in duplicates:flags.append('duplicate_player_identity')
        seen.add(identity)
        if not pid or side not in ('home','away') or str(row.get('team_id'))!=str(event.get(side+'_id')):flags.append('exact_identity_missing')
        if str(row.get('event_id'))!=str(event['event_id']) or row.get('sport')!=sport:flags.append('event_sport_mismatch')
        if row.get('status') not in ('Out','Available'):flags.append('status_uncertain_scenarios_only')
        for key in ('identity_verified','role_verified','workload_verified','source_report_authenticated'):
            if row.get(key) is not True:flags.append(key+'_missing')
        src=source_by_hash.get(row.get('source_sha256'))
        if src is None:flags.append('source_hash_not_captured')
        else:
            try:
                observed=instant(src['observed_at']);published=instant(row['published_at'])
                if not published<=observed<=cut or (cut-published).total_seconds()>86400:flags.append('source_stale_or_after_cutoff')
            except (KeyError,ValueError):flags.append('publication_clock_unverified')
        if not row.get('replacement_identity_verified') or not row.get('replacement_player_ids'):flags.append('replacement_identity_unverified')
        if not finite(row.get('workload')) or not 0<=row['workload']<=1:flags.append('workload_unresolved')
        if sport=='NCAAB':
            if row.get('value_scale')!='NCAAB_INDEPENDENT_POINTS_PER_FULL_ROLE':flags.append('basketball_value_scale_missing')
            if row.get('workload_type') not in ('minutes_share','usage_share'):flags.append('basketball_minutes_or_usage_missing')
        else:
            if row.get('position')=='QB' and not row.get('qb_role_verified'):flags.append('qb_role_unverified')
            if sport=='NFL' and row.get('value_scale')!='NFL_INDEPENDENT_POINTS_PER_FULL_ROLE':flags.append('nfl_value_scale_missing')
        if not finite(row.get('signed_loss')):flags.append('signed_loss_unresolved')
        if flags:unknown.append({'player_id':pid,'side':side,'missing_flags':sorted(set(flags))})
        else:known.append(dict(row))
    return known,unknown


def collect(sport,event,cutoff,private_dir):
    """One capture per URL/UTC date, private raw; inbox is optional and never fabricated.

    event: event_id,kickoff,home_id,away_id. cutoff is a still-future record deadline.
    Public summary/roster/injury feeds are captured as source candidates; their mere
    presence never authenticates a player injury or full report coverage.
    """
    if sport not in SPORT_PATHS:raise ValueError('unsupported sport')
    now=datetime.now(timezone.utc);cut=instant(cutoff);kick=instant(event['kickoff'])
    root=Path(private_dir);root.mkdir(parents=True,exist_ok=True,mode=0o700)
    date=now.date().isoformat();folder=root/sport/date;folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    flags=[];sources=[]
    if not now<=cut<kick:flags.append('capture_deadline_not_future_pregame')
    if (kick-now).total_seconds()>86400:flags.append('fixture_more_than_24h_away')
    base='https://site.api.espn.com/apis/site/v2/sports/'+SPORT_PATHS[sport]
    espn_event=event.get('espn_event_id',event['event_id'])
    urls=[base+'/summary?event='+str(espn_event),base+'/injuries']
    urls += [base+'/teams/'+str(event.get(s+'_espn_id',event.get(s+'_id')))+'/roster' for s in ('home','away') if event.get(s+'_espn_id',event.get(s+'_id'))]
    if sport=='NCAAF':
        for conf in sorted(set(event.get('conferences',[])) & {'SEC','ACC','B12','B10'}):
            urls.append('https://app.hdintelligence.com/api/get-archive-public#'+conf)
    if not flags:
        for url in urls:
            token=hashlib.sha256(url.encode()).hexdigest();receipt_file=folder/(token+'.receipt.json');raw_file=folder/(token+'.json')
            if receipt_file.exists():
                rec=json.loads(receipt_file.read_text())
                if rec.get('status')=='CAPTURED' and (not raw_file.exists() or hashlib.sha256(raw_file.read_bytes()).hexdigest()!=rec.get('sha256')):rec=dict(rec,status='HASH_MISMATCH')
                sources.append(rec);continue
            rec={'url':url,'status':'ERROR_NO_RETRY','observed_at':datetime.now(timezone.utc).isoformat(),'source_publication_at':None,'complete_report_authenticated':False}
            try:
                request=urllib.request.Request(url,headers={'User-Agent':'ProjectCrapsResearch/2'})
                if url.startswith('https://app.hdintelligence.com/api/get-archive-public#'):
                    conf=url.split('#')[1]
                    request=urllib.request.Request(url.split('#')[0],data=json.dumps({'sport':'Football','organization':conf,'conference':conf}).encode(),headers={'User-Agent':'ProjectCrapsResearch/2','Content-Type':'application/json'})
                with urllib.request.urlopen(request,timeout=12) as response:raw=response.read()
                json.loads(raw)
                raw_file.write_bytes(raw);raw_file.chmod(0o600)
                rec.update(status='CAPTURED',sha256=hashlib.sha256(raw).hexdigest(),observed_at=datetime.now(timezone.utc).isoformat())
            except Exception as exc:rec['error_type']=type(exc).__name__
            receipt_file.write_text(json.dumps(rec,indent=2)+'\n');receipt_file.chmod(0o600);sources.append(rec)
    inbox=root/'inbox'/(sport+'_'+str(event['event_id'])+'_'+date+'.json')
    rows=[]
    if inbox.exists():
        data=json.loads(inbox.read_text());rows=data.get('players',[])
        if not isinstance(rows,list):raise ValueError('typed inbox players must be list')
    else:flags.append('verified_player_inbox_missing')
    known,unknown=validate_contributions(rows,sport,event,cutoff,sources)
    flags.extend(['public_endpoint_does_not_establish_complete_injury_coverage','source_authentication_and_manual_attribution_required'])
    if any(s['status']!='CAPTURED' for s in sources):flags.append('one_or_more_public_sources_unavailable')
    return {'sport':sport,'event_id':str(event['event_id']),'cutoff':cutoff,'captured_at':datetime.now(timezone.utc).isoformat(),'sources':sources,'known_contributions':known,'unknown_contributions':unknown,'issueflags':flags,'complete_injury_coverage':False,'research_only':True}


def adjust(base_point,context,model):
    """Apply only independently trained, hash-bound coefficients to known inputs.

    Expected generic model: sport, coefficients{group:value}, identified_groups,
    trained_before, model_sha256, independently_trained=True. No intercept is added:
    bias correction is a separate comparator. Missing contributions stay omitted.
    """
    if not finite(base_point):raise ValueError('finite baseline required')
    result={'status':'NOT_COMPUTED','adjusted_point':None,'injury_delta':None,'known_inputs':len(context.get('known_contributions',[])),'unknown_inputs':len(context.get('unknown_contributions',[])),'research_only':True,'official_changed':False}
    model=model or {}
    sport=context['sport']
    if sport=='NCAAF' and not model and NCAAF_FROZEN_PATH.exists():
        model={'frozen_candidate_path':str(NCAAF_FROZEN_PATH)}
    if sport=='NCAAF' and model.get('frozen_candidate_path'):
        p=Path(model['frozen_candidate_path']);raw=p.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=NCAAF_FROZEN_SHA:raise ValueError('frozen NCAAF candidate hash mismatch')
        frozen=json.loads(raw);co=dict(zip(frozen['shadow_injury_model']['groups'],frozen['shadow_injury_model']['raw_coefficients']))
        result.update(status='FROZEN_ZERO_INJURY_EFFECT_UNIDENTIFIED',adjusted_point=None,injury_delta=0.,coefficients=co,identification=frozen.get('coefficient_identification'),bias_intercept_excluded=True)
        return result
    if model.get('sport')!=sport or model.get('independently_trained') is not True or not model.get('model_sha256'):
        result['reason']='independently_trained_sport_values_missing';return result
    binding={k:v for k,v in model.items() if k!='model_sha256'}
    expected=hashlib.sha256(json.dumps(binding,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    if model['model_sha256']!=expected:raise ValueError('generic sport value model hash mismatch')
    if instant(model['trained_before'])>=instant(context['cutoff']):raise ValueError('model training not before forecast cutoff')
    rows=context.get('known_contributions',[])
    if not rows:result['reason']='no_resolved_injury_inputs';return result
    delta=0.
    for r in rows:
        group=r.get('group');coef=model.get('coefficients',{}).get(group)
        if group not in model.get('identified_groups',[]) or not finite(coef):result['reason']='coefficient_unidentified';return result
        delta += (1 if r['side']=='away' else -1)*coef*r['signed_loss']
    result.update(status='COMPUTED_KNOWN_INPUTS_ONLY',adjusted_point=base_point+delta,injury_delta=delta)
    return result
