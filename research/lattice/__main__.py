import argparse
from pathlib import Path
import numpy as np
from project_craps.common import create,digest,read,unwrap
from research.experiment import PROTOCOL as ORIGINAL_PROTOCOL,compare,masses,metrics
from .model import PROTOCOL,distribution,fit


def run(results,output,registration,minimum=200):
    results=Path(results);output=Path(output);output.mkdir(parents=True,exist_ok=False)
    receipt=unwrap(read(registration))
    if receipt['protocol']!=PROTOCOL:raise ValueError('lattice protocol registration mismatch')
    reports=[];all_before=[];all_after=[]
    for year in ORIGINAL_PROTOCOL['evaluation_seasons']:
        parent=read(results/'fold_models'/(str(year)+'-efficiency.json'))
        calibrator=fit(parent,minimum)
        create(output/(str(year)+'-calibrator.json'),calibrator)
        if year==max(ORIGINAL_PROTOCOL['evaluation_seasons']):create(output/'calibrator.json',calibrator)
        original=read(results/(str(year)+'-efficiency-predictions.json'));corrected=[]
        for row in original:
            scores,w=distribution(parent,calibrator,[row['pred_margin'],row['pred_total']])
            new=dict(row,variant='key_margin_calibrated')
            new['p_home_win']=float(masses(scores,w,'spread',0)[0]);new['pred_tie']=float(w[scores[:,0]==scores[:,1]].sum())
            for key in ('abs_margin_3','abs_margin_7'):
                new['pred_'+key]=float(w[np.abs(scores[:,0]-scores[:,1])==int(key[-1])].sum())
            new['pred_total_60plus']=float(w[scores.sum(axis=1)>=60].sum());new['thresholds']={}
            for key,old in row['thresholds'].items():
                market,line=key.split(':');new['thresholds'][key]={'p':masses(scores,w,market,float(line)).tolist(),'truth':old['truth']}
            corrected.append(new)
        create(output/(str(year)+'-predictions.json'),corrected)
        reports.append({'season':year,'parent':metrics(original),'corrected':metrics(corrected),
                        'paired':compare(original,corrected),'calibration_fit':calibrator['payload']})
        all_before+=original;all_after+=corrected
    report={'protocol':PROTOCOL,'registration':receipt,'sport':parent['payload']['sport'],'folds':reports,
            'pooled':{'parent':metrics(all_before),'corrected':metrics(all_after),'paired':compare(all_before,all_after)},
            'approval':'RESEARCH_ONLY','auto_promotion':False}
    create(output/'report.json',report);return report


def main():
    p=argparse.ArgumentParser();p.add_argument('--results',required=True);p.add_argument('--output',required=True);p.add_argument('--protocol-registration',required=True)
    a=p.parse_args();r=run(a.results,a.output,a.protocol_registration);print(r['sport'],'lattice experiment completed; no promotion')

if __name__=='__main__':main()
