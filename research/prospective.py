"""Private prospective shadow predictions, never released as validated betting p."""
from pathlib import Path
from datetime import timedelta
from project_craps.common import create,digest,instant,now,stamp,unwrap,read
from .context import collect
from .experiment import PROTOCOL,VARIANTS,distribution,fingerprint,masses
from .features import build
from .store import ShadowStore


def observe(snapshot,manifest,nfl,cfb,sacks,metadata,deadlines,hashes,models,registry,output,days=7,max_events=20):
    issued=now();output=Path(output);output.mkdir(parents=True,exist_ok=False)
    for payload in (snapshot['payload'],manifest['payload']):
        for source in payload['sources']:
            if instant(source['observed_at'])>issued:raise ValueError('source captured after as-of cutoff')
    events=sorted((g for g in snapshot['payload']['games'] if g['status']=='SCHEDULED' and g['time_known']
                    and issued<instant(g['kickoff'])<=issued+timedelta(days=days)),key=lambda g:g['kickoff'])[:max_events]
    context=collect(events,metadata,output/'context')
    # Fetching context takes time; recompute issuance and exclude games that started during retrieval.
    issued=now()
    quarantine={r['event_id'] for r in context['events'] if r.get('integrity_failure')}
    events=[g for g in events if instant(g['kickoff'])>issued and g['event_id'] not in quarantine]
    rows=build(snapshot['payload']['games'],metadata,deadlines,nfl,cfb,sacks,events,issued)
    by_id={r['game']['event_id']:r for r in rows}
    artifacts={v:read(Path(models)/(v+'-model.json')) for v in VARIANTS}
    for wrapper in artifacts.values():
        model=unwrap(wrapper)
        if model['implementation_sha256']!=fingerprint() or model['protocol_sha256']!=digest(PROTOCOL):raise ValueError('challenger implementation/protocol changed')
        if model['sport']!=snapshot['payload']['sport']:raise ValueError('challenger sport mismatch')
        if instant(model['built_at'])>issued or instant(model['calibration_last_kickoff'])>=issued:raise ValueError('model not available pregame')
    store=ShadowStore(registry)
    try:
        ids=[]
        for event in events:
            row=by_id[event['event_id']];predictions={}
            for variant,wrapper in artifacts.items():
                model=wrapper['payload'];features=row['features'][variant]
                scores,weights=distribution(model,features)
                diagnostics={}
                for market,lines in [('spread',PROTOCOL['synthetic_home_handicaps']),('total',PROTOCOL['synthetic_total_lines'])]:
                    for line in lines:diagnostics[market+':'+str(line)]=masses(scores,weights,market,line).tolist()
                predictions[variant]={'model_sha256':wrapper['sha256'],'feature_sha256':digest(features),'features':features,
                    'home_win':float(masses(scores,weights,'spread',0)[0]),'home_tie':float(masses(scores,weights,'spread',0)[1]),
                    'synthetic_wpl':diagnostics}
            identity={k:event[k] for k in ('sport','event_id','home_id','away_id','home','away','kickoff')}
            key=digest({'protocol':digest(PROTOCOL),'identity':identity,'sources':hashes,
                        'artifacts':{v:w['sha256'] for v,w in artifacts.items()},'context':digest(context)})
            record={'key':key,'issued_at':stamp(now()),'kickoff':event['kickoff'],'identity':identity,
                'event_id':event['event_id'],'sport':event['sport'],'protocol_sha256':digest(PROTOCOL),
                'source_hashes':hashes,'predictions':predictions,'context_sha256':digest(context),
                'status':'PRIVATE_SHADOW_NOT_A_BETTING_FORECAST','model_approved':False,'approved_risk':0,
                'missing_inputs':['confirmed starting QBs/OL/rosters','validated numerical weather/roster adjustment','authenticated executable quote','independent prospective calibration'],
                'eligibility':'Unadjusted baseline-versus-challenger research comparison only; not recommendation eligible',
                'feature_source_cutoffs':row['stat_cutoffs']}
            saved=store.append(record);ids.append(saved['key'])
        receipt={'issued_at':stamp(now()),'sport':snapshot['payload']['sport'],'records':len(ids),'keys':ids,
            'anchor':store.verify(),'public_probability_released':False,'approved_risk':0,
            'context_sources':len(context['sources']),'context_failures':context['failures'],'quarantined_events':sorted(quarantine),
            'canonical_forecast_or_wager_mutations':0}
        create(output/'receipt.json',receipt)
        return receipt
    finally:store.close()
