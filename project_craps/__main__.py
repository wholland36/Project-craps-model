import argparse
import json
from pathlib import Path
from .common import canonical, create, now, read, stamp
from .data import capture, load_snapshot
from .pipeline import forecast
from .registry import Registry


def main():
    parser = argparse.ArgumentParser(description='Research-only NFL/FBS pipeline. Never places or approves bets.')
    commands = parser.add_subparsers(dest='command', required=True)
    cap = commands.add_parser('capture')
    cap.add_argument('--sport', choices=['NFL', 'NCAAF'], required=True)
    cap.add_argument('--start-year', type=int, required=True)
    cap.add_argument('--end-year', type=int, required=True)
    cap.add_argument('--output', required=True)
    fit = commands.add_parser('train')
    fit.add_argument('--snapshot', required=True)
    fit.add_argument('--output', required=True)
    fit.add_argument('--test-year', type=int, default=2025)
    run = commands.add_parser('forecast')
    run.add_argument('--model', required=True)
    run.add_argument('--snapshot', required=True)
    run.add_argument('--event-id', required=True)
    run.add_argument('--quote')
    run.add_argument('--context')
    run.add_argument('--registry', required=True)
    scan = commands.add_parser('screen')
    scan.add_argument('--model', required=True)
    scan.add_argument('--snapshot', required=True)
    scan.add_argument('--date', required=True, help='Eastern YYYY-MM-DD')
    scan.add_argument('--registry', required=True)
    settle = commands.add_parser('settle-research')
    settle.add_argument('--registry', required=True)
    settle.add_argument('--snapshot', required=True)
    daily = commands.add_parser('daily')
    daily.add_argument('--models', required=True)
    daily.add_argument('--output', required=True)
    daily.add_argument('--registry', required=True)
    daily.add_argument('--quotes')
    daily.add_argument('--context')
    daily.add_argument('--sync', action='store_true')
    for name in ('verify', 'sync', 'prepare-sync', 'ack-sync'):
        cmd = commands.add_parser(name)
        cmd.add_argument('--registry', required=True)
        if name == 'verify':
            cmd.add_argument('--anchor')
        if name in ('prepare-sync', 'ack-sync'):
            cmd.add_argument('--remote', required=True)
            cmd.add_argument('--output', required=True)
        if name == 'ack-sync':
            cmd.add_argument('--prepared', required=True)
    args = parser.parse_args()
    if args.command == 'daily':
        from .daily import run
        result = run(args.models, args.output, args.registry, args.quotes, args.context, args.sync)
        print(canonical(result))
        if any(s['status'] == 'FAILED' for s in result['sports'].values()) or result.get('delivery', {}).get('status') == 'FAILED':
            raise SystemExit(1)
    elif args.command == 'capture':
        wrapper = capture(args.sport, list(range(args.start_year, args.end_year + 1)), args.output)
        print(canonical({'snapshot': str(Path(args.output) / 'snapshot.json'), 'games': len(wrapper['payload']['games']), 'sha256': wrapper['sha256']}))
    elif args.command == 'train':
        from .train import train
        snapshot = load_snapshot(args.snapshot)
        output = Path(args.output)
        output.mkdir(parents=True, exist_ok=False)
        model, report = train(snapshot, args.test_year, tuple(range(args.test_year - 3, args.test_year + 1)))
        create(output / 'model.json', model)
        create(output / 'evaluation.json', report)
        import platform, sys, importlib.metadata
        create(output / 'build_receipt.json', {'code_sha': __import__('subprocess').check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
             'python': sys.version, 'platform': platform.platform(), 'built_at': stamp(now()),
             'model_sha256': model['sha256'], 'snapshot_sha256': snapshot['sha256'],
             'dependencies': {p: importlib.metadata.version(p) for p in ['numpy', 'scipy', 'scikit-learn']}})
        print(canonical({'model': str(output / 'model.json'), 'status': 'RESEARCH_ONLY', 'sha256': model['sha256']}))
    else:
        registry = Registry(args.registry)
        try:
            if args.command == 'settle-research':
                from .settle import settle
                print(canonical({'research_results': settle(registry, load_snapshot(args.snapshot))}))
            elif args.command in ('forecast', 'screen'):
                model, snapshot = read(args.model), load_snapshot(args.snapshot)
                if args.command == 'forecast':
                    record = forecast(model, snapshot, args.event_id, read(args.quote) if args.quote else None,
                                      read(args.context) if args.context else None)
                    print(canonical(registry.append(record)))
                else:
                    from zoneinfo import ZoneInfo
                    from .common import instant
                    if args.date != now().astimezone(ZoneInfo('America/New_York')).date().isoformat():
                        raise ValueError('screen date must be current Eastern date')
                    counts = {'registered': 0, 'started_skipped': 0}
                    for event in snapshot['payload']['games']:
                        if instant(event['kickoff']).astimezone(ZoneInfo('America/New_York')).date().isoformat() != args.date:
                            continue
                        if instant(event['kickoff']) <= now() or event['status'] != 'SCHEDULED':
                            counts['started_skipped'] += 1
                            continue
                        record = forecast(model, snapshot, event['event_id'])
                        registry.append(record)
                        counts['registered'] += 1
                    print(canonical(counts))
            elif args.command == 'verify':
                print(canonical(registry.verify(read(args.anchor) if args.anchor else None)))
            elif args.command == 'sync':
                from .sheets import GoogleTransport, sync
                print(canonical(sync(registry, GoogleTransport())))
            elif args.command == 'prepare-sync':
                from .sheets import plan
                with registry.writer_lock():
                    prepared = plan(registry, read(args.remote))
                    create(args.output, prepared)
                    print(canonical({'append_count': len(prepared['forecast_ids']), 'reconciled': len(prepared['reconciled_ids'])}))
            elif args.command == 'ack-sync':
                from .sheets import acknowledge
                with registry.writer_lock():
                    receipt = acknowledge(registry, read(args.prepared), read(args.remote))
                    create(args.output, receipt)
                    print(canonical(receipt))
        finally:
            registry.close()


if __name__ == '__main__':
    main()
