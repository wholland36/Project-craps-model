import argparse
from pathlib import Path
from project_craps.common import create,envelope,now,stamp
from research.data import capture,fetch


def main():
    p=argparse.ArgumentParser();p.add_argument('--sport',choices=['NFL','NCAAF'],required=True)
    p.add_argument('--start-year',type=int,required=True);p.add_argument('--end-year',type=int,required=True)
    p.add_argument('--output',required=True);a=p.parse_args()
    years=list(range(a.start_year,a.end_year+1));root=Path(a.output);root.mkdir(parents=True,exist_ok=False)
    result=capture(a.sport,years,root/a.sport)
    if result['payload']['failures']:raise RuntimeError('Incomplete public source capture; inspect manifest; no retry performed')
    if a.sport=='NCAAF':
        directory=root/'NCAAF-player-plays';directory.mkdir()
        sources=[]
        for year in years:
            sources.append(fetch(f'https://raw.githubusercontent.com/sportsdataverse/cfbfastR-data/main/player_stats/csv/player_stats_{year}.csv',directory,str(year)))
        create(directory/'manifest.json',envelope({'sources':sources,'captured_at':stamp(now()),'sport':'NCAAF','original_publication_verified':False}))
    print('Public research sources archived:',a.sport,len(years),'seasons')

if __name__=='__main__':main()
