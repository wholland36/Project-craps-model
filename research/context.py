"""Prospective observations, archived at retrieval; never invented injury adjustments."""
import json
from pathlib import Path
import requests
from project_craps.common import bytes_hash, create, envelope, instant, now, stamp


def observe(url,output,label):
    response=requests.get(url,timeout=45)
    response.raise_for_status()
    payload=response.json()
    observed=stamp(now());sha=bytes_hash(response.content)
    raw=Path(output)/(sha+'.json')
    if not raw.exists():raw.write_bytes(response.content)
    receipt={'url':url,'observed_at':observed,'sha256':sha,'raw_file':raw.name,
             'original_publication_at':None,'label':label}
    create(Path(output)/(label+'-source.json'),receipt)
    return payload,receipt


def collect(events,metadata,output):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    result={'captured_at':stamp(now()),'events':[],'sources':[],'failures':[],'approved_risk':0}
    injuries={}
    for sport in sorted({g['sport'] for g in events}):
        path='nfl' if sport=='NFL' else 'college-football'
        url='https://site.api.espn.com/apis/site/v2/sports/football/'+path+'/injuries'
        try:
            data,receipt=observe(url,output,sport+'-injuries')
            injuries[sport]=data;result['sources'].append(receipt)
        except (requests.RequestException,ValueError) as error:
            result['failures'].append({'source':url,'error_type':type(error).__name__})
    for event in events:
        if event['status']!='SCHEDULED' or instant(event['kickoff'])<=now():
            result['failures'].append({'event_id':event['event_id'],'error_type':'STARTED_OR_UNSCHEDULED'})
            continue
        sport=event['sport'];path='nfl' if sport=='NFL' else 'college-football'
        eid=metadata[event['event_id']]['espn_event_id']
        url='https://site.api.espn.com/apis/site/v2/sports/football/'+path+'/summary?event='+eid
        row={'event_id':event['event_id'],'sport':sport,'kickoff':event['kickoff'],
             'quarterback':'UNRESOLVED','offensive_line':'UNRESOLVED','roster':'UNRESOLVED',
             'weather':'UNRESOLVED','executable_quote':'UNAVAILABLE','injury_adjustment':'NOT_COMPUTED'}
        try:
            summary,receipt=observe(url,output,sport+'-'+event['event_id'])
            result['sources'].append(receipt)
            header=summary.get('header',{})
            if str(header.get('id'))!=str(eid):raise ValueError('summary event ID mismatch')
            competitions=header.get('competitions',[])
            if not competitions or competitions[0].get('status',{}).get('type',{}).get('state')!='pre':
                raise ValueError('summary does not confirm pregame status')
            if instant(competitions[0]['date'])!=instant(event['kickoff']):raise ValueError('summary kickoff mismatch')
            competitors=competitions[0].get('competitors',[])
            for role in ('home','away'):
                matching=[c for c in competitors if c.get('homeAway')==role]
                if len(matching)!=1:raise ValueError('summary home/away identity missing')
                team=matching[0].get('team',{})
                # NFL canonical names are abbreviations; FBS team IDs are provider-native ESPN IDs.
                if sport=='NCAAF' and str(team.get('id'))!=event[role+'_id']:raise ValueError('summary team ID mismatch')
                if sport=='NFL' and team.get('abbreviation')!=event[role+'_id']:raise ValueError('summary team abbreviation mismatch')
            weather=summary.get('gameInfo',{}).get('weather')
            row['weather_observation']=weather
            row['weather']='OBSERVED_FORECAST_NOT_ADJUSTED' if weather else 'UNRESOLVED'
            row['pregame_status_verified']=True
            row['source_sha256']=receipt['sha256']
            # Preserve raw rosters/injuries instead of treating absence of an injury tag as confirmed starter.
            row['roster_payload_present']=bool(summary.get('rosters'))
            row['team_injury_payload_present']=bool(injuries.get(sport))
        except (requests.RequestException,ValueError,KeyError) as error:
            row['error_type']=type(error).__name__
            row['pregame_status_verified']=False
        row['observed_at']=stamp(now())
        result['events'].append(row)
    create(output/'context.json',envelope(result))
    return result
