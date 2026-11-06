#!/usr/bin/env python3
"""Benchmark minimap-click routes using passive Z-Route map responses.

Commands:
  screenshot: save emulator screenshot and print its native pixel dimensions.
  plan:       generate a pixel-coordinate grid within a USER-VERIFIED minimap ROI.
  run:        optionally click each target and capture the resulting map response.
  compare:    replay the observed base IDs in several orders, without more clicks.

Only --execute performs ADB taps. No direct game-server requests are sent.
Requires the existing scan.py, live_watch.py and zroute_map_decoder.py alongside.
Captured traffic and player CSVs are private; do not commit network_scans/.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
import struct
import subprocess
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from live_watch import resolve_interface, traffic_stats
from scan import BASE_FIELDS, inspect, save_csv


PATTERNS = ('snake', 'checkerboard', 'spiral', 'spread')
RESULT_FIELDS = ('step', 'target_id', 'row', 'col', 'tap_x', 'tap_y',
                 'seconds', 'views', 'base_observations', 'new_bases',
                 'total_unique', 'received_bytes', 'decode_errors', 'status', 'capture')
COMPARE_FIELDS = ('pattern', 'observed_targets', 'available_unique_bases',
                  'unique_first_25pct', 'unique_first_50pct', 'unique_first_75pct',
                  'clicks_to_50pct', 'clicks_to_90pct', 'travel_pixels',
                  'estimated_seconds')
PROGRESS_FIELDS = ('pattern', 'click', 'target_id', 'new_bases', 'cumulative_unique')


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def load_adb_settings(args):
    """Use the same ADB executable and serial as the existing scanner."""
    config_path = Path(__file__).resolve().parent.parent / 'config.json'
    cfg = {}
    if config_path.is_file():
        try:
            cfg = json.loads(config_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError) as exc:
            raise SystemExit(f'Cannot read {config_path}: {exc}') from exc
    args.adb = args.adb or cfg.get('adb_path') or 'adb'
    args.serial = args.serial or cfg.get('adb_serial') or '127.0.0.1:5555'
    if not shutil.which(args.adb):
        raise SystemExit(
            f'ADB executable not found: {args.adb!r}. '
            'Set adb_path in config.json or supply --adb with the full path to adb.exe. '
            'No game clicks were performed.')
    print(f'ADB: {args.adb} (device {args.serial})', flush=True)


def ensure_adb_device(args):
    """Reconnect ONLY the explicitly configured local TCP Android device."""
    def call(*parts):
        try:
            return subprocess.run([args.adb, *parts], capture_output=True, text=True,
                                  errors='replace', timeout=12)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f'ADB check failed: {exc}') from exc

    status = call('devices', '-l')
    if status.returncode:
        raise RuntimeError('adb devices failed: ' + status.stderr.strip())
    def is_connected(output):
        return any(line.split()[:2] == [args.serial, 'device']
                   for line in output.splitlines())
    if is_connected(status.stdout):
        return
    if args.serial.startswith('127.0.0.1:') or args.serial.startswith('localhost:'):
        print(f'ADB device {args.serial} missing. Trying adb connect...', flush=True)
        result = call('connect', args.serial)
        print((result.stdout or result.stderr).strip(), flush=True)
        status = call('devices', '-l')
        if is_connected(status.stdout):
            return
    raise RuntimeError(
        f'ADB device {args.serial!r} is not connected. Run "{args.adb}" devices -l '
        'to see available devices. Enable Android Debug Bridge in BlueStacks settings, '
        'and update config.json adb_serial if the BlueStacks port is different. '
        'No game clicks were performed.')

def adb_run(adb, serial, *argv, timeout=20, binary=False):
    args = [adb, '-s', serial, *argv]
    try:
        result = subprocess.run(args, capture_output=True, timeout=timeout,
                                text=not binary)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError('ADB unavailable; stopped without additional clicks: ' + str(exc)) from exc
    if result.returncode:
        error = result.stderr.decode(errors='replace') if binary else result.stderr
        raise RuntimeError('ADB command failed: ' + error.strip())
    return result.stdout


def screenshot(args):
    raw = adb_run(args.adb, args.serial, 'exec-out', 'screencap', '-p',
                  timeout=35, binary=True)
    if raw[:8] != b'\x89PNG\r\n\x1a\n' or len(raw) < 24:
        raise RuntimeError('ADB did not produce a PNG screenshot.')
    width, height = struct.unpack_from('>II', raw, 16)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(raw)
    print(f'Saved {args.out} ({width} x {height} emulator pixels).')
    print('Open this image in Paint and record the TOP-LEFT and BOTTOM-RIGHT')
    print('pixel coordinates of the CLICKABLE minimap region, excluding UI buttons.')
    print('Use those four values in plan --roi left,top,right,bottom.')


def parse_roi(value):
    try:
        roi = [int(v.strip()) for v in value.split(',')]
    except ValueError as exc:
        raise argparse.ArgumentTypeError('Expected --roi left,top,right,bottom') from exc
    if len(roi) != 4 or roi[0] < 0 or roi[1] < 0 or roi[2] <= roi[0] or roi[3] <= roi[1]:
        raise argparse.ArgumentTypeError('Invalid ROI. Expected left,top,right,bottom.')
    return roi


def targets(rows, cols, roi, inset=0.05):
    left, top, right, bottom = roi
    if not 0 <= inset < 0.3:
        raise ValueError('inset must be 0 through 0.29')
    width = right - left
    height = bottom - top
    points = []
    for r in range(rows):
        for c in range(cols):
            x = round(left + width * (inset + (1 - 2 * inset) * (c + 0.5) / cols))
            y = round(top + height * (inset + (1 - 2 * inset) * (r + 0.5) / rows))
            points.append(dict(id=f'r{r:02d}c{c:02d}', row=r, col=c, x=x, y=y))
    return points


def ordered(points, pattern):
    if pattern == 'snake':
        return sorted(points, key=lambda p: (p['row'],
                      p['col'] if p['row'] % 2 == 0 else -p['col']))
    if pattern == 'checkerboard':
        snake = ordered(points, 'snake')
        return sorted(snake, key=lambda p: (p['row'] + p['col']) % 2)
    if pattern == 'spiral':
        # Center outwards; deterministic on even or odd grids.
        cy = (max(p['row'] for p in points)) / 2
        cx = (max(p['col'] for p in points)) / 2
        return sorted(points, key=lambda p: (max(abs(p['row'] - cy), abs(p['col'] - cx)),
                   math.atan2(p['row'] - cy, p['col'] - cx)))
    if pattern == 'spread':
        # Greedy maximin sampling of the minimap, no player data used.
        remaining = list(points)
        chosen = []
        cy = statistics.mean(p['y'] for p in points)
        cx = statistics.mean(p['x'] for p in points)
        first = max(remaining, key=lambda p: (p['x']-cx)**2 + (p['y']-cy)**2)
        chosen.append(first)
        remaining.remove(first)
        while remaining:
            point = max(remaining, key=lambda p:
                        (min((p['x']-q['x'])**2 + (p['y']-q['y'])**2 for q in chosen),
                         -((p['x']-cx)**2 + (p['y']-cy)**2),
                         -p['row'], -p['col']))
            chosen.append(point)
            remaining.remove(point)
        return chosen
    raise ValueError('Unknown pattern: ' + pattern)


def plan(args):
    if not 2 <= args.rows <= 12 or not 2 <= args.cols <= 12:
        raise SystemExit('--rows/--cols must each be 2..12')
    if args.out.exists() and not args.force:
        raise SystemExit('Plan already exists; use another --out or --force.')
    points = targets(args.rows, args.cols, args.roi, args.inset)
    config = {'schema': 1, 'created_at': utcnow(), 'rows': args.rows,
              'cols': args.cols, 'roi': args.roi, 'inset': args.inset, 'targets': points}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(config, indent=2), encoding='utf-8')
    print(f'Planned {len(points)} click positions within emulator ROI {args.roi}.')
    for pattern in PATTERNS:
        route = ordered(points, pattern)
        preview = args.out.with_name(args.out.stem + '_' + pattern + '.csv')
        save_csv(preview, ('step', 'target_id', 'tap_x', 'tap_y'),
                 [dict(step=i, target_id=p['id'], tap_x=p['x'], tap_y=p['y'])
                  for i, p in enumerate(route, 1)])
        print(f'  {pattern:13} {preview}  first clicks: ' +
              ', '.join(p['id'] for p in route[:5]))
    print('No clicks performed. Verify ROI and generated coordinates first.')


def load_plan(path):
    document = json.loads(path.read_text(encoding='utf-8'))
    pts = document.get('targets', [])
    if document.get('schema') != 1 or not pts:
        raise SystemExit('Unsupported or empty plan JSON.')
    return document


def verify_device(adb, serial, rectangle):
    raw = adb_run(adb, serial, 'exec-out', 'screencap', '-p',
                  timeout=35, binary=True)
    if raw[:8] != b'\x89PNG\r\n\x1a\n':
        raise RuntimeError('Unable to verify emulator screen dimensions.')
    width, height = struct.unpack_from('>II', raw, 16)
    left, top, right, bottom = rectangle
    if left < 0 or top < 0 or right > width or bottom > height:
        raise SystemExit(f'ROI {rectangle} lies outside actual emulator screen {width}x{height}.')
    print(f'ADB screen: {width}x{height}; minimap click ROI: {rectangle}.')


def save_state(path, plan_checksum, pattern, entries):
    content = {'schema': 1, 'plan_sha256': plan_checksum, 'pattern': pattern,
               'updated_at': utcnow(), 'entries': entries}
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(content, indent=2), encoding='utf-8')
    temp.replace(path)


def summarize(entries, out):
    save_csv(out / 'steps.csv', RESULT_FIELDS, entries)
    unique = set()
    for e in entries:
        unique.update(e.get('player_ids', []))
    print(f'Completed {len(entries)} click attempts; '
          f'{len(unique)} distinct bases discovered in this benchmark.')


def run(args):
    document = load_plan(args.plan)
    pts = ordered(document['targets'], args.pattern)
    plan_hash = hashlib.sha256(args.plan.read_bytes()).hexdigest()
    session = args.out or Path('network_scans/pattern_benchmark') / args.pattern
    session.mkdir(parents=True, exist_ok=True)
    state_path = session / 'observations.json'
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding='utf-8'))
        if state['plan_sha256'] != plan_hash or state['pattern'] != args.pattern:
            raise SystemExit('Existing session has different plan or pattern; choose a new --out.')
        entries = state['entries']
    else:
        entries = []
    done = {e['target_id'] for e in entries}
    unique = {identifier for e in entries for identifier in e.get('player_ids', [])}
    planned = [p for p in pts if p['id'] not in done]
    if args.max_clicks:
        planned = planned[:args.max_clicks]
    print(f'Pattern={args.pattern} | planned={len(pts)} | remaining in this test={len(planned)}')
    if not args.execute:
        for p in planned:
            print(f'  PREVIEW {p["id"]}: tap emulator ({p["x"]},{p["y"]})')
        print('No clicks made. Add --execute after verifying the ROI and map is open.')
        return
    verify_device(args.adb, args.serial, document['roi'])
    if not 3 <= args.capture_seconds <= 60 or not 0.2 <= args.settle <= 5:
        raise SystemExit('capture-seconds 3..60; settle 0.2..5 seconds required.')
    device = resolve_interface(args.dumpcap, args.interface)
    captures = session / 'captures'
    captures.mkdir(exist_ok=True)
    print('IMPORTANT: Keep the map open, minimap visible, and zoom unchanged.')
    print('Only the game minimap receives clicks. Ctrl+C saves the checkpoint.')
    for p in planned:
        idx = len(entries) + 1
        capture = captures / f'{idx:03d}_{p["id"]}.pcapng'
        command = [args.dumpcap, '-i', device, '-f', 'tcp port 9929',
                   '-a', f'duration:{args.capture_seconds}', '-w', str(capture)]
        started = time.monotonic()
        proc = None
        try:
            with (session / 'dumpcap.log').open('a', encoding='utf-8') as log:
                proc = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=log)
                time.sleep(0.5)
                if proc.poll() is not None:
                    raise RuntimeError('dumpcap exited early; check dumpcap.log')
                adb_run(args.adb, args.serial, 'shell', 'input', 'tap',
                        str(p['x']), str(p['y']))
                proc.wait(timeout=args.capture_seconds + 12)
                if proc.returncode:
                    raise RuntimeError('dumpcap failed; check dumpcap.log')
            views, failures = inspect(capture)
            stats = traffic_stats(capture)
            identities = set()
            observations = 0
            centers = []
            for view, bases in views:
                observations += len(bases)
                centers.append((view['center_x'], view['center_y']))
                identities.update(str(b['server']) + ':' + str(b['player_id'])
                                  for b in bases if b.get('player_id'))
            additions = len(identities - unique)
            unique.update(identities)
            status = ('NO_GAME_TRAFFIC' if not stats['incoming_packets']
                      else 'NO_MAP_RESPONSE' if not views
                      else 'NO_NEW_PLAYER_IDS' if not additions else 'OK')
            entry = dict(step=idx, target_id=p['id'], row=p['row'], col=p['col'],
                         tap_x=p['x'], tap_y=p['y'], seconds=round(time.monotonic()-started, 2),
                         views=len(views), base_observations=observations,
                         new_bases=additions, total_unique=len(unique),
                         received_bytes=stats['incoming_bytes'],
                         decode_errors=failures, status=status, capture=str(capture),
                         player_ids=sorted(identities), centers=centers, observed_at=utcnow())
            entries.append(entry)
            save_state(state_path, plan_hash, args.pattern, entries)
            summarize(entries, session)
            print(f'[{idx}/{len(pts)}] {p["id"]}: +{additions} NEW | '
                  f'{len(unique)} UNIQUE | {len(views)} views | {status}', flush=True)
            if idx == 1 and status != 'OK':
                print('FIRST CLICK WAS NOT VALIDATED. Stopping to avoid scanning '
                      'an incorrect minimap region. Inspect game UI/ROI and PCAP.')
                break
            time.sleep(args.settle)
        except KeyboardInterrupt:
            print('Interrupted: observations saved through last completed click.')
            break
        except (OSError, RuntimeError, subprocess.TimeoutExpired, ValueError) as exc:
            print('HALTED after click failure:', exc)
            print('Review the minimap and capture configuration before resuming.')
            break
        finally:
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
    print('Session folder:', session)


def compare(args):
    data = json.loads((args.session / 'observations.json').read_text(encoding='utf-8'))
    document = load_plan(args.plan)
    expected = hashlib.sha256(args.plan.read_bytes()).hexdigest()
    if data['plan_sha256'] != expected:
        raise SystemExit('Plan does not match saved observations.')
    by_target = {e['target_id']: set(e['player_ids'])
                 for e in data['entries'] if e.get('views', 0)}
    pts = [p for p in document['targets'] if p['id'] in by_target]
    if len(pts) < 2:
        raise SystemExit('Need at least two successfully decoded target positions.')
    all_ids = set().union(*(by_target[p['id']] for p in pts))
    n = len(pts)
    elapsed = [e['seconds'] for e in data['entries'] if e.get('seconds')]
    typical_seconds = statistics.median(elapsed) if elapsed else 0
    steps = []
    overview = []

    routes = {pattern: ordered(pts, pattern) for pattern in PATTERNS}
    # Greedy uses the ALREADY OBSERVED ID sets. It is an offline upper bound,
    # not a claim that live navigation can know unvisited player identities.
    leftover, picked, discovered = pts.copy(), [], set()
    while leftover:
        prev = picked[-1] if picked else None
        def value(p):
            gain = len(by_target[p['id']] - discovered)
            dist = math.hypot(p['x'] - prev['x'], p['y'] - prev['y']) if prev else 0
            return (gain, -dist, -p['row'], -p['col'])
        chosen = max(leftover, key=value)
        picked.append(chosen)
        discovered |= by_target[chosen['id']]
        leftover.remove(chosen)
    routes['greedy_oracle'] = picked

    for pattern, route in routes.items():
        seen, counts, travel, previous = set(), [], 0.0, None
        for number, p in enumerate(route, 1):
            ids = by_target[p['id']]
            gain = len(ids - seen)
            seen |= ids
            counts.append(len(seen))
            if previous:
                travel += math.hypot(p['x']-previous['x'], p['y']-previous['y'])
            steps.append(dict(pattern=pattern, click=number, target_id=p['id'],
                              new_bases=gain, cumulative_unique=len(seen)))
            previous = p
        def reach(fraction):
            target = math.ceil(fraction * len(all_ids))
            return next((i for i, total in enumerate(counts, 1) if total >= target), '')
        def at(fraction):
            return counts[max(1, math.ceil(n * fraction)) - 1]
        overview.append(dict(pattern=pattern, observed_targets=n,
                             available_unique_bases=len(all_ids),
                             unique_first_25pct=at(.25), unique_first_50pct=at(.5),
                             unique_first_75pct=at(.75),
                             clicks_to_50pct=reach(.5), clicks_to_90pct=reach(.9),
                             travel_pixels=round(travel, 1),
                             estimated_seconds=round(n*typical_seconds, 1)))
    overview.sort(key=lambda r: (r['clicks_to_90pct'], -r['unique_first_50pct']))
    save_csv(args.session / 'comparison.csv', COMPARE_FIELDS, overview)
    save_csv(args.session / 'comparison_progress.csv', PROGRESS_FIELDS, steps)
    print(f'Compared {len(pts)} observed minimap locations with '
          f'{len(all_ids)} unique decoded base IDs.')
    if n != len(document['targets']):
        print(f'CAUTION: only {n}/{len(document["targets"])} grid locations '
              'had decoded responses. This is a partial comparison.')
    for result in overview:
        print(f'{result["pattern"]:14}  90% after '
              f'{result["clicks_to_90pct"]:>3} clicks | '
              f'50% clicks -> {result["unique_first_50pct"]:>6} bases | '
              f'travel {result["travel_pixels"]:>7} px')
    print('greedy_oracle is a retrospective best-first benchmark, not a live policy.')
    print('All patterns eventually cover the SAME measured positions, so the '
          'full-scan unique total is identical.')
    print('Saved comparison.csv and comparison_progress.csv in', args.session)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    s = commands.add_parser('screenshot', help='Save native BlueStacks screenshot for ROI calibration')
    s.add_argument('--out', type=Path, default=Path('network_scans/minimap_reference.png'))
    s.add_argument('--adb', help='Override config.json adb_path')
    s.add_argument('--serial', help='Override config.json adb_serial')
    s.set_defaults(fn=screenshot)

    p = commands.add_parser('plan', help='Generate safe preview paths: no game clicks')
    p.add_argument('--roi', type=parse_roi, required=True,
                   help='Clickable minimap pixel rectangle: left,top,right,bottom')
    p.add_argument('--rows', type=int, default=4)
    p.add_argument('--cols', type=int, default=4)
    p.add_argument('--inset', type=float, default=.07)
    p.add_argument('--out', type=Path, default=Path('network_scans/minimap_grid.json'))
    p.add_argument('--force', action='store_true')
    p.set_defaults(fn=plan)

    r = commands.add_parser('run', help='Preview route; --execute allows real minimap taps')
    r.add_argument('--plan', type=Path, required=True)
    r.add_argument('--pattern', choices=PATTERNS, default='snake')
    r.add_argument('--interface', default='Wi-Fi')
    r.add_argument('--dumpcap', default='dumpcap')
    r.add_argument('--adb', help='Override config.json adb_path')
    r.add_argument('--serial', help='Override config.json adb_serial')
    r.add_argument('--capture-seconds', type=int, default=6)
    r.add_argument('--settle', type=float, default=.5)
    r.add_argument('--max-clicks', type=int, default=0, help='0=entire grid; try 1 first')
    r.add_argument('--out', type=Path, help='Session folder; reused to resume')
    r.add_argument('--execute', action='store_true', help='Explicitly permit ADB minimap taps')
    r.set_defaults(fn=run)

    c = commands.add_parser('compare', help='Replay all patterns against observed player sets')
    c.add_argument('--session', type=Path, required=True)
    c.add_argument('--plan', type=Path, required=True)
    c.set_defaults(fn=compare)
    args = parser.parse_args()
    if args.command == 'screenshot' or (args.command == 'run' and args.execute):
        load_adb_settings(args)
        ensure_adb_device(args)
    args.fn(args)


if __name__ == '__main__':
    main()
