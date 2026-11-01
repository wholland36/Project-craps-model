"""Matched descriptive benchmarks. Source prices/ratings lack original publication evidence."""
import argparse
import csv
import io
from pathlib import Path
from project_craps.common import bytes_hash,create,read
from research.data import number
from research.experiment import binary_metrics,compare


def benchmark_report(results_path,snapshot_path,output):
    results=Path(results_path);source=read(snapshot_path);games=source['payload']['games']
    sport=source['payload']['sport'];reference={}
    for item in source['payload']['sources']:
        raw=(Path(snapshot_path).parent/(item['sha256']+'.csv')).read_bytes()
        if bytes_hash(raw)!=item['sha256']:raise ValueError('benchmark raw source hash mismatch')
        for row in csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))):
            if sport=='NFL':
                home,away=number(row.get('home_moneyline')),number(row.get('away_moneyline'))
                if home is None or away is None or abs(home)<100 or abs(away)<100:continue
                implied=lambda z:-z/(100-z) if z<0 else 100/(100+z)
                hp,ap=implied(home),implied(away);p=hp/(hp+ap)
            else:
                home,away=number(row.get('home_pregame_elo')),number(row.get('away_pregame_elo'))
                if home is None or away is None:continue
                p=1/(1+10**((away-home)/400))
            reference[str(row['game_id'])]=p
    report=read(results/'report.json')
    output_report={'sport':sport,'benchmark':'source-snapshot no-vig moneyline' if sport=='NFL' else 'source-reported pregame Elo',
        'original_publication_times_verified':False,'book_execution_verified':False,
        'scope':'Post-fit matched descriptive diagnostic, not contemporaneously authenticated betting evidence.',
        'probability_definition':'conditional non-tie; actual ties excluded, model p divided by 1-p(tie)',
        'variants':{},'approved_risk':0}
    for variant in report['protocol']['variants']:
        paired=[];bench=[];seasons={}
        for year in report['protocol']['evaluation_seasons']:
            models=[];baselines=[]
            for row in read(results/(str(year)+'-'+variant+'-predictions.json')):
                if row['event_id'] not in reference or row['actual_margin']==0 or row['pred_tie']>=1:continue
                m=dict(row,p_home_win=row['p_home_win']/(1-row['pred_tie']))
                b=dict(row,p_home_win=reference[row['event_id']])
                models.append(m);baselines.append(b)
            paired+=models;bench+=baselines
            seasons[str(year)]={'matched_n':len(models),'model':binary_metrics([r['p_home_win'] for r in models],[r['actual_home_win'] for r in models]) if models else None,
                 'benchmark':binary_metrics([r['p_home_win'] for r in baselines],[r['actual_home_win'] for r in baselines]) if baselines else None}
        output_report['variants'][variant]={'seasons':seasons,'paired_model_minus_benchmark':compare(bench,paired) if paired else None}
    create(output,output_report)
    return output_report


def main():
    p=argparse.ArgumentParser();p.add_argument('--results',required=True);p.add_argument('--snapshot',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();r=benchmark_report(a.results,a.snapshot,a.output)
    print(r['sport'],r['benchmark'],'diagnostic complete')

if __name__=='__main__':main()
