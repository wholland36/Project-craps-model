"""Bounded, unauthenticated public sample download; no subscriptions or retries.
Raw files stay local. Attribute The Odds Gap; do not redistribute as a feed.
"""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import requests

URLS = {
    'odds': 'https://theoddsgap.com/api/odds-export.csv?sport=americanfootball_ncaaf',
    'results-college': 'https://theoddsgap.com/api/team-results-export?league=college-football',
    'page': 'https://theoddsgap.com/data',
    'terms': 'https://theoddsgap.com/terms',
    'college': 'https://theoddsgap.com/data/college-football',
}


def fetch(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=False,mode=0o700)
    manifest=[]
    for name,url in URLS.items():
        receipt=dict(name=name,url=url,requested_at=datetime.now(timezone.utc).isoformat())
        try:
            response=requests.get(url,timeout=90)
            raw=response.content
            with (output/(name+'.raw')).open('xb') as target:target.write(raw)
            receipt.update(status=response.status_code,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),
                           received_at=datetime.now(timezone.utc).isoformat(),
                           headers={k:v for k,v in response.headers.items() if k.lower().startswith(('x-','content-type','date','last-modified'))})
        except requests.RequestException as exc:
            receipt['failure']=type(exc).__name__
        manifest.append(receipt)
    with (output/'download-manifest.json').open('x') as target:json.dump(manifest,target,indent=2)
    return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();result=fetch(args.output)
    print(json.dumps([dict(name=r['name'],status=r.get('status'),bytes=r.get('bytes'),failure=r.get('failure')) for r in result]))
