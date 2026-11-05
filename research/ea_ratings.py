"""Download the public EA CFB ratings roster; construct rating-gap research priors."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from hashlib import sha256
from html.parser import HTMLParser
import json
import math
import os
from pathlib import Path
import requests

URL='https://www.ea.com/games/ea-sports-college-football/ratings'
GROUPS={**{p:p for p in ['QB','HB','FB','WR','TE','C','DT','CB','K','P']},
        'LT':'OT','RT':'OT','LG':'OG','RG':'OG','LEDG':'EDGE','REDG':'EDGE',
        'MIKE':'LB','WILL':'LB','SAM':'LB','MLB':'LB','LOLB':'LB','ROLB':'LB','LE':'EDGE','RE':'EDGE','FS':'S','SS':'S'}


class NextData(HTMLParser):
    def __init__(self):super().__init__();self.active=False;self.parts=[]
    def handle_starttag(self,tag,attrs):
        if tag=='script' and dict(attrs).get('id')=='__NEXT_DATA__':self.active=True
    def handle_endtag(self,tag):
        if tag=='script':self.active=False
    def handle_data(self,data):
        if self.active:self.parts.append(data)


def stamp():return datetime.now(timezone.utc).isoformat()


def normalize(item):
    overall=item['overallRating']
    if type(overall) is not int or not 0<=overall<=99:raise ValueError('invalid OVR')
    if item['stats']['overall']['value']!=overall:raise ValueError('overall fields disagree')
    position=item['position']['id']
    if position not in GROUPS:raise ValueError('unmapped position '+position)
    return {'ea_player_id':str(item['id']),'player_name':item['firstName']+' '+item['lastName'],
            'ea_team_id':str(item['team']['id']),'team':item['team']['label'],
            'position':position,'position_group':GROUPS[position],'overall_rating':overall,
            'school_year':item.get('schoolYear'),'iteration':item['iteration']['id'],
            'attributes':{k:v['value'] for k,v in item['stats'].items()}}


def collect(output,workers=3,iteration=None):
    output=Path(output)
    if output.exists():raise ValueError('refusing to overwrite capture')
    output.mkdir(parents=True,mode=0o700)
    first=requests.get(URL,params={'iteration':iteration} if iteration else None,timeout=50,allow_redirects=False);first.raise_for_status()
    parser=NextData();parser.feed(first.text);data=json.loads(''.join(parser.parts))
    props=data['props']['pageProps'];details=props['ratingDetails'];total=details['totalItems']
    requested_iteration=iteration
    iteration=requested_iteration or props['ratingsFilters']['iterations'][0]['id'];size=len(details['items'])
    if not total or not size or not all(x['iteration']['id']==iteration for x in details['items']):raise ValueError('initial rating iteration inconsistent')
    rawdir=output/'private-source';rawdir.mkdir(mode=0o700)
    rawdir.joinpath('page-001.html').write_bytes(first.content)
    receipts=[{'page':1,'url':URL,'received_at':stamp(),'sha256':sha256(first.content).hexdigest(),'items':size}]
    pages=math.ceil(total/size);all_items=list(details['items'])
    endpoint=f"https://www.ea.com/_next/data/{data['buildId']}/en/games/ea-sports-college-football/ratings.json"
    def fetch(page):
        response=requests.get(endpoint,params={'page':page,'iteration':iteration,'franchiseSlug':'ea-sports-college-football'},timeout=50,allow_redirects=False)
        response.raise_for_status();body=response.json()['pageProps']['ratingDetails']
        if body['totalItems']!=total:raise ValueError('roster changed during capture')
        expected=size if page<pages else total-size*(pages-1)
        if len(body['items'])!=expected or any(x['iteration']['id']!=iteration for x in body['items']):raise ValueError('pagination or iteration mismatch')
        rawdir.joinpath(f'page-{page:03d}.json').write_bytes(response.content)
        return body['items'],{'page':page,'url':response.url,'received_at':stamp(),'sha256':sha256(response.content).hexdigest(),'items':len(body['items'])}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for items,receipt in executor.map(fetch,range(2,pages+1)):
            all_items.extend(items);receipts.append(receipt)
            if receipt['page']%20==0:print('Captured page',receipt['page'],'of',pages,flush=True)
    (output/'source-receipts.json').write_text(json.dumps(receipts,indent=2)+'\n')
    if len(all_items)!=total:raise ValueError('incomplete raw roster')
    unique={}
    for item in all_items:
        key=str(item['id'])
        if key in unique and unique[key]!=item:raise ValueError('conflicting duplicate EA player ID')
        unique[key]=item
    rows=[normalize(x) for x in unique.values()]
    rows.sort(key=lambda r:(-r['overall_rating'],r['player_name'],r['ea_player_id']))
    (output/'players.json').write_text(json.dumps(rows,indent=2)+'\n')
    manifest={'source_url':first.url,'game':props['gameDetails']['name'],'iteration':iteration,
              'iteration_label':next(x['label'] for x in props['ratingsFilters']['iterations'] if x['id']==iteration),
              'source_reported_total':total,'downloaded_raw_rows':len(all_items),'downloaded_unique_players':len(rows),'duplicate_rows':len(all_items)-len(rows),'identity_coverage_complete':len(rows)==total,'pages':pages,
              'teams':len({r['ea_team_id'] for r in rows}),'captured_at':stamp(),
              'original_publication_at':None,'source_time_authentication':'Observation time only; publication/update date not independently established',
              'players_sha256':sha256((output/'players.json').read_bytes()).hexdigest(),'page_receipts':receipts,
              'usage':'Current research talent prior only. Not real-world points, depth-chart order, current health, or historical pregame evidence.'}
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest


def rating_gap(starter,replacement,expected_snap_share=1.):
    """Signed raw gap and nonnegative 0..1 proxy; never auto-pick a backup."""
    if starter['ea_player_id']==replacement['ea_player_id']:raise ValueError('replacement must be a different player')
    if starter['ea_team_id']!=replacement['ea_team_id']:raise ValueError('replacement must be on same team')
    if starter['position_group']!=replacement['position_group']:raise ValueError('incompatible replacement role')
    if starter['iteration']!=replacement['iteration']:raise ValueError('mixed rating vintages')
    if isinstance(expected_snap_share,bool) or not isinstance(expected_snap_share,(int,float)) or not math.isfinite(expected_snap_share) or not 0<=expected_snap_share<=1:raise ValueError('snap share must be 0..1')
    for player in (starter,replacement):
        if type(player['overall_rating']) is not int or not 0<=player['overall_rating']<=99:raise ValueError('invalid rating range')
    gap=starter['overall_rating']-replacement['overall_rating']
    return {'starter_id':starter['ea_player_id'],'replacement_id':replacement['ea_player_id'],
            'position_group':starter['position_group'],'overall_rating_gap':gap,
            'snap_weighted_rating_loss':max(0,gap)*expected_snap_share,
            'normalized_rating_loss':max(0,gap)/100*expected_snap_share,
            'expected_points_over_replacement':None,'points_conversion':'NOT_CALIBRATED',
            'source_interpretation':'EA video-game talent rating prior, not measured real-world player value',
            'approved_risk_usd':0}


def scale_reports(reports, players, manifest, asof):
    from project_craps.common import instant
    if instant(manifest['captured_at'])>instant(asof):raise ValueError('ratings captured after forecast cutoff')
    ids={p['ea_player_id']:p for p in players}
    if len(ids)!=len(players):raise ValueError('duplicate EA player IDs')
    results=[];issues=[]
    for r in reports:
        if r.get('ea_identity_verified') is not True:
            issues.append('injury-to-EA identity crosswalk unverified');continue
        starter=ids.get(str(r.get('ea_player_id')));backup=ids.get(str(r.get('ea_replacement_player_id')))
        if starter is None or backup is None:
            issues.append('named starter or actual replacement absent from EA roster');continue
        if starter['ea_team_id']!=str(r['ea_team_id']):raise ValueError('injury/EA team identity mismatch')
        if starter['iteration']!=manifest['iteration']:raise ValueError('ratings manifest iteration mismatch')
        results.append(rating_gap(starter,backup,r['expected_lost_snap_share']))
    return {'status':'RESEARCH_RATING_PRIOR_ONLY','rating_loss_features':results,'missing_inputs':issues,
            'roster_iteration':manifest['iteration'],'roster_sha256':manifest['players_sha256'],
            'scoring_point_adjustment':None,'points_conversion':'NOT_CALIBRATED','production_approved':False}


def load_roster(folder):
    folder=Path(folder);manifest=json.loads((folder/'manifest.json').read_text());raw=(folder/'players.json').read_bytes()
    if sha256(raw).hexdigest()!=manifest['players_sha256']:raise ValueError('EA roster hash mismatch')
    players=json.loads(raw)
    if len(players)!=manifest['downloaded_unique_players'] or len({p['ea_player_id'] for p in players})!=len(players):raise ValueError('roster coverage or identity mismatch')
    if any(p['iteration']!=manifest['iteration'] for p in players):raise ValueError('mixed roster iterations')
    return players,manifest


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True);p.add_argument('--iteration');a=p.parse_args()
    os.umask(0o077);m=collect(a.output,iteration=a.iteration);print(json.dumps({k:m[k] for k in ['game','iteration','downloaded_unique_players','teams','pages','players_sha256']}))


if __name__=='__main__':main()
