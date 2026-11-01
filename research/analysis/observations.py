"""Index raw prospective quote/weather/roster observations without making adjustments."""
import argparse
from pathlib import Path
from project_craps.common import bytes_hash,create,instant,read,stamp,now,unwrap
from research.data import load,raw_rows


def index(context_path,annual_manifest,output):
    path=Path(context_path);data=unwrap(read(path));sources={s['sha256']:s for s in data['sources']}
    observations=[]
    for event in data['events']:
        if not event.get('pregame_status_verified') or not event.get('source_sha256'):continue
        source=sources[event['source_sha256']]
        raw=(path.parent/source['raw_file']).read_bytes()
        if bytes_hash(raw)!=source['sha256']:raise ValueError('context archive changed')
        payload=__import__('json').loads(raw)
        if instant(source['observed_at'])>=instant(event['kickoff']):raise ValueError('postgame observation is ineligible')
        quotes=payload.get('pickcenter',[])
        observations.append({'event_id':event['event_id'],'sport':event['sport'],
            'observed_at':source['observed_at'],'source_url':source['url'],'source_sha256':source['sha256'],
            'weather':payload.get('gameInfo',{}).get('weather'),
            'roster_payload_present':bool(payload.get('rosters')),
            'quarterback_confirmed':False,'offensive_line_confirmed':False,
            'quote_observations':quotes,'book_quote_original_publication_at':None,
            'quotes_verified_executable':False,'quote_interpretation':'Raw provider fields only; no Hard Rock substitution, price comparison, EV, or CLV claim.'})
    annual=[]
    if annual_manifest:
        manifest=load(annual_manifest)
        for source in manifest['payload']['sources']:
            if source['label'].startswith(('cfb_returning_production','cfb_team_portal')):
                rows=raw_rows(Path(annual_manifest).parent,source)
                annual.append({'label':source['label'],'rows':len(rows),'fields':sorted(rows[0]) if rows else [],
                    'observed_at':source['observed_at'],'source_sha256':source['sha256'],
                    'historical_training_eligible':False,'reason':'Original publication/roster-effective timestamps unverified; archived for prospective use only.'})
    result={'indexed_at':stamp(now()),'observations':observations,'annual_covariates':annual,
            'quote_observation_count':sum(len(r['quote_observations']) for r in observations),
            'weather_observation_count':sum(bool(r['weather']) for r in observations),'approved_risk':0}
    create(output,result)
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--context',required=True);p.add_argument('--annual-manifest');p.add_argument('--output',required=True)
    a=p.parse_args();r=index(a.context,a.annual_manifest,a.output)
    print('Indexed',len(r['observations']),'pregame events;',r['quote_observation_count'],'raw provider quote observations;',len(r['annual_covariates']),'annual source files')

if __name__=='__main__':main()
