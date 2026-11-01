import argparse
from datetime import timedelta
from pathlib import Path
from project_craps.common import canonical,create,digest,envelope,instant,now,read,stamp,unwrap
from project_craps.data import load_snapshot
from .data import cfb_metrics,load,nfl_metrics,raw_rows,schedule_metadata
from .features import build,player_sacks


def inputs(snapshot_path,metrics_path,player_path=None):
    snapshot=load_snapshot(snapshot_path)
    metric_manifest=load(metrics_path)
    if snapshot['payload']['sport']!=metric_manifest['payload']['sport']:raise ValueError('metrics sport mismatch')
    nfl,cfb,sacks,coverage={},{},{},{}
    for source in metric_manifest['payload']['sources']:
        if not source['label'].isdigit():continue
        rows=raw_rows(Path(metrics_path).parent,source)
        values=nfl_metrics(rows) if snapshot['payload']['sport']=='NFL' else cfb_metrics(rows)
        target=nfl if snapshot['payload']['sport']=='NFL' else cfb
        if set(target)&set(values):raise ValueError('duplicate metric records across source years')
        target.update(values)
    hashes={'schedule':snapshot['sha256'],'metrics':metric_manifest['sha256']}
    if snapshot['payload']['sport']=='NCAAF':
        if not player_path:raise ValueError('attributed player-play archive is required for actual FBS sacks')
        player_manifest=load(player_path)
        sacks,coverage=player_sacks(Path(player_path).parent,player_manifest['payload']['sources'],snapshot['payload']['games'])
        hashes['player_plays']=player_manifest['sha256']
    metadata,deadlines=schedule_metadata(snapshot,Path(snapshot_path).parent)
    return snapshot,metric_manifest,nfl,cfb,sacks,coverage,metadata,deadlines,hashes


def main():
    parser=argparse.ArgumentParser(description='Frozen baseline diagnostics and zero-risk football challengers')
    subs=parser.add_subparsers(dest='command',required=True)
    for name in ('experiment','observe'):
        p=subs.add_parser(name)
        p.add_argument('--snapshot',required=True);p.add_argument('--metrics',required=True)
        p.add_argument('--player-metrics');p.add_argument('--output',required=True)
        if name=='experiment':p.add_argument('--protocol-registration',required=True)
        else:
            p.add_argument('--models',required=True);p.add_argument('--registry',required=True)
            p.add_argument('--days',type=int,default=7);p.add_argument('--max-events',type=int,default=20)
    settle=subs.add_parser('settle');settle.add_argument('--snapshot',required=True);settle.add_argument('--registry',required=True)
    verify=subs.add_parser('verify');verify.add_argument('--registry',required=True)
    args=parser.parse_args()
    if args.command in ('verify','settle'):
        from .store import ShadowStore
        store=ShadowStore(args.registry)
        try:
            if args.command=='verify':result=store.verify()
            else:
                source=load_snapshot(args.snapshot)['payload']
                result=store.settle(source['games'],source['captured_at'])
            print(canonical(result))
        finally:store.close()
        return
    snapshot,manifest,nfl,cfb,sacks,coverage,metadata,deadlines,hashes=inputs(args.snapshot,args.metrics,args.player_metrics)
    if args.command=='experiment':
        from .experiment import run
        receipt=unwrap(read(args.protocol_registration))
        from .experiment import PROTOCOL
        if receipt['protocol']!=PROTOCOL:raise ValueError('registered protocol differs from experiment design')
        rows=build(snapshot['payload']['games'],metadata,deadlines,nfl,cfb,sacks)
        report=run(rows,args.output,receipt,hashes)
        create(Path(args.output)/'coverage.json',{'source_failures':manifest['payload']['failures'],
            'feature_rows':len(rows),'efficiency_complete_rows':sum(r['efficiency_complete'] for r in rows),
            'attributed_player_coverage':coverage,
            'tempo_definition':'play-volume proxy, not measured seconds per snap',
            'annual_roster_features':'archived but not fitted: original publication timestamps unverified'})
        print(canonical({'sport':snapshot['payload']['sport'],'folds':len(report['folds']),'variants':len(PROTOCOL['variants']),'output':args.output,'approval':'RESEARCH_ONLY'}))
    else:
        from .prospective import observe
        result=observe(snapshot,manifest,nfl,cfb,sacks,metadata,deadlines,hashes,args.models,args.registry,args.output,args.days,args.max_events)
        print(canonical(result))


if __name__=='__main__':main()
