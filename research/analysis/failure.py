"""Supplement fixed diagnostics with attributed-play overtime labels and paired ablations."""
import argparse
import csv
from collections import defaultdict
from pathlib import Path
from project_craps.common import bytes_hash,create,read
from research.data import load
from research.experiment import compare,groups,metrics


def overtime_labels(manifest_path,event_ids):
    manifest=load(manifest_path);root=Path(manifest_path).parent
    periods=defaultdict(int)
    for source in manifest['payload']['sources']:
        with (root/source['file']).open() as stream:
            for row in csv.DictReader(stream):
                eid=str(row['game_id'])
                if eid in event_ids:
                    try:periods[eid]=max(periods[eid],int(float(row['period'])))
                    except (KeyError,ValueError):pass
    return {eid:(value>4 if value>=4 else None) for eid,value in periods.items()}


def summarize(results_path,output,player_manifest=None):
    root=Path(results_path);report=read(root/'report.json')
    predictions={}
    for variant in report['protocol']['variants']:
        predictions[variant]=[]
        for year in report['protocol']['evaluation_seasons']:
            predictions[variant]+=read(root/(str(year)+'-'+variant+'-predictions.json'))
    ot=overtime_labels(player_manifest,{r['event_id'] for r in predictions['original']}) if player_manifest else {}
    for values in predictions.values():
        for row in values:
            if ot:row['actual_overtime']=ot.get(row['event_id'])
    result={'sport':report['sport'],'diagnostic_only':True,'model_or_forecast_mutations':0,
        'overtime_label_source':'max observed attributed-play period; <4 or missing remains UNKNOWN' if player_manifest else 'nflverse schedule overtime flag',
        'overtime_coverage':sum(r['actual_overtime'] is not None for r in predictions['original']),
        'n_unique_test_events':len(predictions['original']),'variants':{},'component_comparisons':{}}
    for variant,values in predictions.items():
        result['variants'][variant]={'metrics':metrics(values),'groups':groups(values),
            'small_group_warning':'Group estimates below n=100 are descriptive and unstable; no subgroup staking or threshold tuning.'}
    for a,b in [('original','scaled'),('scaled','opponent_score'),('opponent_score','efficiency'),('efficiency','score_kernel')]:
        result['component_comparisons'][b+' minus '+a]=compare(predictions[a],predictions[b])
    create(output,result)
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--results',required=True);p.add_argument('--output',required=True);p.add_argument('--player-metrics')
    a=p.parse_args();r=summarize(a.results,a.output,a.player_metrics)
    print(r['sport'],'failure-analysis complete; unique events',r['n_unique_test_events'],'OT label coverage',r['overtime_coverage'])

if __name__=='__main__':main()
