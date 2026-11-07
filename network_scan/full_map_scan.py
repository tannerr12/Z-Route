#!/usr/bin/env python3
"""Progressive, passive Z-Route minimap scanner.

Center-out stages (default 4x4, 7x7, 10x10) plus optional refinements.
Clicks only the USER-verified BlueStacks minimap via ADB. Reads server
responses from local dumpcap captures; no direct game-server requests.

Examples:
  python network_scan/full_map_scan.py run
  python network_scan/full_map_scan.py run --execute --max-clicks 4
  python network_scan/full_map_scan.py run --execute
  python network_scan/full_map_scan.py run --execute --stages 4,7,10,13
  python network_scan/full_map_scan.py report
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from pattern_benchmark import (
    adb_run, ensure_adb_device, load_adb_settings, ordered, parse_roi,
    targets, verify_device,
)
from live_watch import resolve_interface, traffic_stats
from player_history import connection, ingest_records
from scan import BASE_FIELDS, inspect, load_csv, save_csv

STEPS_FIELDS = ('number', 'stage', 'target_id', 'tap_x', 'tap_y', 'status',
                'attempts', 'seconds', 'map_views', 'observations', 'new_ids',
                'cumulative_ids', 'centers', 'capture', 'incoming_bytes',
                'decode_errors', 'updated_at')


def stages_arg(text):
    try:
        values = [int(s.strip()) for s in text.split(',')]
    except ValueError as exc:
        raise argparse.ArgumentTypeError('Stages must be comma-separated grid sizes') from exc
    if not values or any(not 2 <= n <= 25 for n in values):
        raise argparse.ArgumentTypeError('Grid sizes must be between 2 and 25')
    if values != sorted(set(values)):
        raise argparse.ArgumentTypeError('Stages must be increasing with no repeats')
    return values


def route(roi, stages, inset, min_separation, pattern='spiral'):
    """Build progressive stages with selected route, omitting repeated taps."""
    points = []
    for size in stages:
        for p in ordered(targets(size, size, roi, inset), pattern):
            if any((p['x']-q['tap_x'])**2 + (p['y']-q['tap_y'])**2 <
                   min_separation**2 for q in points):
                continue
            points.append(dict(number=len(points)+1, stage=size,
                               target_id=f'{size}x{size}_{p["id"]}',
                               tap_x=p['x'], tap_y=p['y']))
    return points


def signature(config):
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode('utf-8')).hexdigest()


def player_key(player):
    server = str(player.get('server', '')).strip()
    identifier = str(player.get('player_id', '')).strip()
    return f'{server}:{identifier}' if server and identifier else None


def atomic_json(path, data):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)


def write_outputs(folder, record, players):
    # Persist player IDs before marking a target complete, so an interrupted
    # write cannot checkpoint a view while silently losing its discoveries.
    save_csv(folder / 'players.csv', BASE_FIELDS,
             sorted(players.values(), key=lambda p: player_key(p) or ''))
    latest = {p['target_id']: p for p in record['entries']}
    ordered_rows = sorted(latest.values(), key=lambda r: r['number'])
    save_csv(folder / 'steps.csv', STEPS_FIELDS, ordered_rows)
    atomic_json(folder / 'checkpoint.json', record)


def load_players(path):
    players = {}
    if path.is_file():
        for p in load_csv(path):
            key = player_key(p)
            if key:
                players[key] = p
    return players


def summary(record, players, route_points, goal):
    latest = {p['target_id']: p for p in record['entries']}
    finished = [p for p in latest.values() if p['status'] in ('OK', 'OVERLAP', 'EMPTY')]
    reviews = [p for p in latest.values() if p['status'] not in ('OK', 'OVERLAP', 'EMPTY')]
    centers = {tuple(x) for p in latest.values() for x in p.get('centers', [])}
    print(f'Observed {len(players):,} / ~{goal:,} target bases '
          f'({len(players)/goal*100:.1f}% of target). '
          f'Completed {len(finished)}/{len(route_points)} clicks; '
          f'{len(reviews)} review; {len(centers)} unique map centers.')
    missing = max(0, len(route_points) - len(finished) - len(reviews))
    print(f'Coverage: {len(finished):,} confirmed / {len(route_points):,} planned '
          f'({len(finished)/max(1,len(route_points))*100:.1f}%); '
          f'{missing:,} not attempted; {len(reviews):,} need review. '
          'Unique-ID target is not proof of full map coverage.')
    if len(players)>=goal:
        print(f'Roster milestone >= {goal:,} reached; route still continues '
              'unless --stop-at-goal was explicitly requested.')
    if record['entries']:
        total_seconds = sum(float(p['seconds']) for p in record['entries'])
        if total_seconds > 0:
            print(f'Capture elapsed: {total_seconds/60:.1f} minutes; '
                  f'{len(players)*60/total_seconds:.1f} unique IDs per minute '
                  f'(includes repeats, not an estimate of total population).')
    for stage in sorted({p['stage'] for p in route_points}):
        group = [p for p in latest.values() if p['stage'] == stage]
        if group:
            new_ids = sum(int(p['new_ids']) for p in group)
            print(f'  {stage}x{stage}: {len(group)} attempted, +{new_ids} new IDs')
    print('Note: this is observed player count, NOT verified geographic coverage.')


def build(args):
    args.out.mkdir(parents=True, exist_ok=True)
    pattern=getattr(args,'pattern','spiral')
    cfg = dict(roi=args.roi, inset=args.inset, min_separation=args.min_separation)
    all_points = route(args.roi, args.stages, args.inset, args.min_separation, pattern)
    # Preserve old spiral checkpoints (their route.json has no pattern key).
    if pattern!='spiral':
        cfg['pattern']=pattern
    plan_path = args.out / 'route.json'
    if plan_path.exists():
        prior = json.loads(plan_path.read_text(encoding='utf-8'))
        if prior['config'] != cfg:
            raise SystemExit('Existing run uses different ROI/inset/min-distance. '
                             'Choose another --out for a new calibration.')
        old_points = prior['points']
        if all_points[:len(old_points)] != old_points:
            raise SystemExit('Existing route is not a prefix of this route. '
                             'To extend, append a larger grid size to --stages; '
                             'otherwise use another --out.')
    else:
        old_points = []
    if all_points != old_points:
        atomic_json(plan_path, dict(schema=1, config=cfg,
                                    stages=args.stages, points=all_points))
    save_csv(args.out / 'route.csv',
             ('number', 'stage', 'target_id', 'tap_x', 'tap_y'), all_points)
    return all_points


def capture_click(args, point, attempt, device, captures):
    duration = args.seconds + max(0, attempt-1)*args.retry_extra
    file = captures / (f'{point["number"]:03d}_{point["target_id"]}'
                       f'_try{attempt}.pcapng')
    cmd = [args.dumpcap, '-i', device, '-f', 'tcp port 9929',
           '-a', f'duration:{duration}', '-w', str(file)]
    started = time.monotonic()
    proc = None
    with (args.out / 'dumpcap.log').open('a', encoding='utf-8') as log:
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=log)
            time.sleep(.45)
            if proc.poll() is not None:
                raise RuntimeError('dumpcap ended immediately; see dumpcap.log')
            try:
                adb_run(args.adb, args.serial, 'shell', 'input', 'tap',
                        str(point['tap_x']), str(point['tap_y']), timeout=15)
            except RuntimeError:
                # ADB may time out after a tap; retrying the identical minimap
                # target is safe once this configured emulator reconnects.
                ensure_adb_device(args)
                raise RuntimeError('ADB tap failed; device rechecked. Retrying target.')
            try:
                proc.wait(timeout=duration+15)
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError('dumpcap timed out; see dumpcap.log') from exc
            if proc.returncode != 0:
                raise RuntimeError('dumpcap failed; see dumpcap.log')
            views, failures = inspect(file)
            traffic = traffic_stats(file)
            players = {}
            observed = 0
            centers = []
            for view, bases in views:
                observed += len(bases)
                centers.append([int(view['center_x']), int(view['center_y'])])
                for p in bases:
                    key = player_key(p)
                    if key:
                        players[key] = p
            if not traffic['incoming_packets']:
                status = 'NO_TRAFFIC'
            elif not views:
                status = 'NO_MAP_RESPONSE'
            elif not players:
                status = 'EMPTY'
            else:
                status = 'OK'
            return dict(status=status, players=players, centers=centers,
                        views=len(views), observations=observed,
                        seconds=round(time.monotonic()-started, 2),
                        incoming_bytes=traffic['incoming_bytes'],
                        errors=failures, capture=str(file))
        finally:
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=6)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)


def scan(args):
    if not 0 <= args.inset < .3 or not 1 <= args.min_separation <= 25:
        raise SystemExit('--inset must be 0..0.29; --min-separation 1..25')
    if not 3 <= args.seconds <= 30 or not 1 <= args.retries <= 5:
        raise SystemExit('--seconds must be 3..30; --retries 1..5')
    if args.retry_extra < 0 or args.goal < 1 or args.max_clicks < 0:
        raise SystemExit('Bad retry/goal/max-clicks setting')
    points = build(args)
    state_path = args.out / 'checkpoint.json'
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding='utf-8'))
    else:
        state = dict(schema=1, created_at=datetime.now(timezone.utc).isoformat(),
                     entries=[])
    players = load_players(args.out / 'players.csv')
    latest = {p['target_id']: p for p in state['entries']}
    pending = [p for p in points
               if p['target_id'] not in latest
               or (args.retry_review and latest[p['target_id']]['status']
                   not in ('OK', 'OVERLAP', 'EMPTY'))]
    if args.max_clicks:
        pending = pending[:args.max_clicks]
    print(f'{getattr(args,"pattern","spiral")} route: {len(points)} distinct minimap clicks '
          f'({",".join(str(n)+"x"+str(n) for n in args.stages)}).')
    print(f'Existing: {len(players):,} unique bases, '
          f'{len(latest)} visited targets; {len(pending)} pending this run.')
    if not args.execute:
        print('PREVIEW ONLY: no game clicks or network capture.')
        for p in pending[:25]:
            print(f'  {p["number"]:03d}: {p["stage"]}x{p["stage"]} '
                  f'tap ({p["tap_x"]}, {p["tap_y"]})')
        print('Use --execute to start. Start with --max-clicks 4.')
        return
    if not pending:
        print('No pending targets. Use --retry-review or extend --stages if needed.')
        summary(state, players, points, args.goal)
        return
    load_adb_settings(args)
    ensure_adb_device(args)
    verify_device(args.adb, args.serial, args.roi)
    device = resolve_interface(args.dumpcap, args.interface)
    captures = args.out / 'captures'
    captures.mkdir(exist_ok=True)
    print('KEEP MINIMAP OPEN and ZOOM FIXED. Ctrl+C stops after saving the last click.')
    clicks_run = 0
    consecutive_unconfirmed = 0
    for p in pending:
        if args.stop_at_goal and len(players) >= args.goal:
            print(f'Goal of ~{args.goal:,} reached; stopping by request. '
                  'Check geographic gaps separately.')
            break
        first = len(players)
        result = None
        for attempt in range(1, args.retries+1):
            print(f'Click {p["number"]}/{len(points)} '
                  f'({p["stage"]}x{p["stage"]}) target {p["target_id"]} '
                  f'at ({p["tap_x"]},{p["tap_y"]}) try {attempt}/{args.retries}',
                  flush=True)
            try:
                result = capture_click(args, p, attempt, device, captures)
                if result['status'] in ('OK', 'EMPTY'):
                    break
                print(f'  {result["status"]}; retrying with longer capture...',
                      flush=True)
            except KeyboardInterrupt:
                print('\nInterrupted; previous clicks remain saved.', flush=True)
                summary(state, players, points, args.goal)
                return
            except (OSError, ValueError, RuntimeError) as exc:
                print('  Capture/ADB error:', exc, flush=True)
                if 'ADB device' in str(exc) or 'Cannot' in str(exc):
                    print('Device state uncertain. Stopping instead of blindly clicking.',
                          flush=True)
                    summary(state, players, points, args.goal)
                    return
                result = dict(status='ERROR', players={}, centers=[],
                              views=0, observations=0, seconds=0,
                              incoming_bytes=0, errors=1, capture='')
        if result is None:
            continue
        for key, player in result['players'].items():
            players[key] = player
        additions = len(players) - first
        status = ('OVERLAP' if result['status'] == 'OK' and additions == 0
                  else result['status'])
        entry = dict(number=p['number'], stage=p['stage'], target_id=p['target_id'],
                     tap_x=p['tap_x'], tap_y=p['tap_y'], status=status,
                     attempts=attempt, seconds=result['seconds'],
                     map_views=result['views'], observations=result['observations'],
                     new_ids=additions, cumulative_ids=len(players),
                     centers=result['centers'], capture=result['capture'],
                     incoming_bytes=result['incoming_bytes'],
                     decode_errors=result['errors'],
                     updated_at=datetime.now(timezone.utc).isoformat())
        # Name history is more important than a finished click checkpoint.
        # Save each capture's identities first, before a later roster update
        # can replace the old username. A failed write leaves this target
        # pending for a safe retry and the underlying PCAP untouched.
        try:
            with connection(getattr(args, 'history_db', Path('network_scans/player_history.sqlite3'))) as history:
                ingest_records(history, result['players'].values(),
                               result['capture'], observed_at=entry['updated_at'])
        except Exception as exc:
            print('ERROR: name history could not be preserved:', exc, flush=True)
            print('Stopped without checkpointing this click. Capture is still at:',
                  result['capture'], flush=True)
            return
        state['entries'].append(entry)
        write_outputs(args.out, state, players)
        clicks_run += 1
        # A misaligned map or dead capture interface must not generate
        # hundreds of blind minimap clicks. Keep checkpoint + evidence.
        if status in ('OK','OVERLAP','EMPTY'):
            consecutive_unconfirmed = 0
        else:
            consecutive_unconfirmed += 1
        print(f'  +{additions} NEW | {len(players):,} UNIQUE / ~{args.goal:,} '
              f'({len(players)/args.goal*100:.1f}%) | '
              f'{result["views"]} views | {status}', flush=True)
        if consecutive_unconfirmed >= 3:
            print('STOPPED: 3 consecutive minimap targets returned no '
                  'confirmed map response. Check zoom, ROI, ADB, and dumpcap. '
                  'The checkpoint and captures are saved; do not continue '
                  'blindly.',flush=True)
            summary(state, players, points, args.goal)
            return
        if clicks_run % 10 == 0:
            summary(state, players, points, args.goal)
    print('Scan run ended. Progress and captures saved in:', args.out)
    summary(state, players, points, args.goal)


def report(args):
    state_path = args.out / 'checkpoint.json'
    if not state_path.is_file():
        raise SystemExit(f'No checkpoint in {args.out}')
    record = json.loads(state_path.read_text(encoding='utf-8'))
    route_path = args.out / 'route.json'
    points = json.loads(route_path.read_text(encoding='utf-8'))['points']
    players = load_players(args.out / 'players.csv')
    summary(record, players, points, args.goal)
    latest = {p['target_id']: p for p in record['entries']}
    problem = [p for p in latest.values()
               if p['status'] not in ('OK', 'OVERLAP', 'EMPTY')]
    if problem:
        print(f'{len(problem)} targets need review / retry:')
        for p in problem[:25]:
            print(' ', p['target_id'], p['status'], p.get('centers', []))


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    run = commands.add_parser('run', help='Preview or execute a progressive minimap scan')
    run.add_argument('--roi', type=parse_roi, default=[800, 25, 1060, 270],
                     help='BlueStacks screenshot pixel bounds: L,T,R,B')
    run.add_argument('--stages', type=stages_arg, default=[4, 7, 10],
                     help='Increasing grid sizes, e.g. 4,7,10 or 4,7,10,13')
    run.add_argument('--pattern', choices=('spiral','spread','snake','checkerboard'),
                     default='spiral',
                     help='Within-stage visiting order; spiral is original default')
    run.add_argument('--inset', type=float, default=.07)
    run.add_argument('--min-separation', type=float, default=8,
                     help='Skip minimap clicks within this many pixels of past targets')
    run.add_argument('--out', type=Path, default=Path('network_scans/full_map'))
    run.add_argument('--history-db', type=Path,
                     default=Path('network_scans/player_history.sqlite3'),
                     help='Shared append-only player identity/name history across every scan session')
    run.add_argument('--interface', default='Wi-Fi')
    run.add_argument('--dumpcap', default='dumpcap')
    run.add_argument('--adb', help='Override config.json adb_path')
    run.add_argument('--serial', help='Override config.json adb_serial')
    run.add_argument('--seconds', type=int, default=4, help='Initial capture seconds per click')
    run.add_argument('--retry-extra', type=int, default=3,
                     help='Add seconds on each retry (default +3)')
    run.add_argument('--retries', type=int, default=2)
    run.add_argument('--goal', type=int, default=9700)
    run.add_argument('--stop-at-goal', action='store_true',
                     help='Opt in to early stop at goal (not complete coverage proof)')
    run.add_argument('--retry-review', action='store_true',
                     help='Retry saved targets lacking confirmed map responses')
    run.add_argument('--max-clicks', type=int, default=0,
                     help='Limit new clicks in THIS invocation; 0 means all')
    run.add_argument('--execute', action='store_true',
                     help='Actually click BlueStacks minimap; default is preview')
    run.set_defaults(fn=scan)
    rep = commands.add_parser('report', help='Report saved unique IDs and scan gaps')
    rep.add_argument('--out', type=Path, default=Path('network_scans/full_map'))
    rep.add_argument('--goal', type=int, default=9700)
    rep.set_defaults(fn=report)
    args = parser.parse_args()
    args.fn(args)


if __name__ == '__main__':
    main()
