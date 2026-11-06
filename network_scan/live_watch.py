#!/usr/bin/env python3
"""Live read-only counter of unique Z-Route bases while navigating in BlueStacks.

    python network_scan/live_watch.py --interface 1 --dumpcap "C:\Program Files\Wireshark\dumpcap.exe" --segment-seconds 15

Captures only existing traffic. It does not talk to the game server.
Map responses may cross dumpcap's rotated PCAPNG boundaries, so every closed
segment is decoded together with its immediate predecessor.

Counts refer to observed unique player IDs, NOT full-server coverage.
Keep PCAPNGs and player CSVs private. Ctrl+C finalizes the active segment.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from scan import BASE_FIELDS, VIEW_FIELDS, inspect, load_csv, save_csv
from zroute_map_decoder import read_packets, TCP_PORT

SEGMENT_FIELDS = ('filename', 'processed_at', 'incoming_packets', 'incoming_bytes',
                  'outgoing_packets', 'outgoing_bytes', 'decoded_map_views',
                  'new_view_signatures', 'base_observations', 'new_bases',
                  'total_unique', 'decode_failures', 'status')
WATCH_VIEW_FIELDS = tuple(VIEW_FIELDS) + ('signature',)


def base_key(player):
    server = str(player.get('server', '')).strip()
    identifier = str(player.get('player_id', '')).strip()
    return (server, identifier) if server and identifier else None


def traffic_stats(path):
    incoming_packets = incoming_bytes = outgoing_packets = outgoing_bytes = 0
    for key, _, _, payload in read_packets(path):
        if key[1] == TCP_PORT:
            incoming_packets += 1
            incoming_bytes += len(payload)
        elif key[3] == TCP_PORT:
            outgoing_packets += 1
            outgoing_bytes += len(payload)
    return dict(incoming_packets=incoming_packets, incoming_bytes=incoming_bytes,
                outgoing_packets=outgoing_packets, outgoing_bytes=outgoing_bytes)


def view_signature(view, bases):
    # Stable across rereads of overlapping capture windows.
    identity = ','.join(sorted(str(base_key(p)) for p in bases if base_key(p)))
    basis = '|'.join((str(view['center_x']), str(view['center_y']),
                      str(view['payload_bytes']), identity))
    return hashlib.sha256(basis.encode('utf-8')).hexdigest()[:24]


def decode_with_predecessor(file, previous_file, out):
    if previous_file is None:
        return inspect(file)
    # Multiple PCAPNG sections are allowed. A shared TCP sequence space
    # lets the decoder complete a map response crossing the file boundary.
    joined = out / '.joined_preview.pcapng'
    try:
        with joined.open('wb') as dest:
            for source in (previous_file, file):
                with source.open('rb') as stream:
                    shutil.copyfileobj(stream, dest)
        return inspect(joined)
    finally:
        joined.unlink(missing_ok=True)


def process_segment(file, previous_file, players, view_rows, segments, out, seen_views):
    stats = traffic_stats(file)
    decoded, errors = decode_with_predecessor(file, previous_file, out)
    newly_found = newly_seen_views = observations = 0
    for view, bases in decoded:
        signature = view_signature(view, bases)
        if signature in seen_views:
            continue
        seen_views.add(signature)
        newly_seen_views += 1
        record = dict(view)
        record['capture'] = file.name + (' (includes previous segment)' if previous_file else '')
        record['signature'] = signature
        view_rows.append(record)
        observations += len(bases)
        for player in bases:
            key = base_key(player)
            if key is None:
                continue
            if key not in players:
                newly_found += 1
            players[key] = player
    failures = errors if isinstance(errors, int) else errors.get('decode_error', 0)
    if stats['incoming_packets'] == 0:
        status = 'NO_INCOMING_GAME_TRAFFIC'
    elif not decoded:
        status = 'NO_MAP_RESPONSE_DECODED'
    elif newly_seen_views == 0:
        status = 'OVERLAPPING_OR_REPEATED_VIEWS'
    elif newly_found == 0:
        status = 'NO_NEW_PLAYER_IDS'
    else:
        status = 'NEW_BASES'
    segments.append(dict(filename=file.name, processed_at=datetime.now(timezone.utc).isoformat(),
                         decoded_map_views=len(decoded), new_view_signatures=newly_seen_views,
                         base_observations=observations, new_bases=newly_found,
                         total_unique=len(players), decode_failures=failures,
                         status=status, **stats))
    save_csv(out / 'players.csv', BASE_FIELDS,
             sorted(players.values(), key=lambda p: base_key(p) or ('', '')))
    save_csv(out / 'views.csv', WATCH_VIEW_FIELDS, view_rows)
    save_csv(out / 'segments.csv', SEGMENT_FIELDS, segments)
    centers = {(str(v['center_x']), str(v['center_y'])) for v in view_rows}
    print(f'[{datetime.now().strftime("%H:%M:%S")}] '
          f'+{newly_found} NEW | {len(players)} UNIQUE TOTAL | '
          f'{len(centers)} distinct centers | '
          f'{newly_seen_views} new views | '
          f'{stats["incoming_packets"]} incoming packets ({stats["incoming_bytes"]:,} bytes) | '
          f'{status}', flush=True)
    if status == 'NO_INCOMING_GAME_TRAFFIC':
        print('  Check dumpcap interface (-D), that Z-Route is open, and port 9929.',
              flush=True)
    elif status == 'NO_MAP_RESPONSE_DECODED':
        print('  Game traffic was captured, but no complete map response was found. '
              'Jump/zoom to a NEW region and check the next segment.',
              flush=True)


def watch(args):
    if args.recount:
        if not args.out or not args.out.is_dir():
            raise SystemExit('--recount requires --out pointing to an existing scan session folder')
        capture_dir = args.out / 'captures'
        files = sorted(capture_dir.glob('zroute*.pcapng'),
                       key=lambda p: (p.stat().st_mtime_ns, p.name))
        if not files:
            raise SystemExit('No saved PCAPNG segments in ' + str(capture_dir))
        print(f'Recounting {len(files)} saved capture segments without starting Wireshark.')
        players, views, segments, seen_views = {}, [], [], set()
        for i, file in enumerate(files):
            process_segment(file, files[i - 1] if i else None,
                            players, views, segments, args.out, seen_views)
        print(f'RECOUNT COMPLETE: {len(players)} unique observed bases.')
        return
    if not args.interface:
        raise SystemExit('--interface is required unless using --recount')
    if not 3 <= args.segment_seconds <= 120:
        raise SystemExit('--segment-seconds must be between 3 and 120')
    out = args.out or (Path('network_scans') / 'live' /
                       datetime.now().strftime('%Y%m%d_%H%M%S'))
    out.mkdir(parents=True, exist_ok=True)
    captures = out / 'captures'
    captures.mkdir(exist_ok=True)
    players = {}
    if (out / 'players.csv').exists():
        for player in load_csv(out / 'players.csv'):
            key = base_key(player)
            if key:
                players[key] = player
    views = load_csv(out / 'views.csv') if (out / 'views.csv').exists() else []
    segments = load_csv(out / 'segments.csv') if (out / 'segments.csv').exists() else []
    seen_views = {str(v.get('signature', '')) for v in views if v.get('signature')}
    done = {r['filename'] for r in segments}
    before_count = len(players)

    print('Output:', out.resolve())
    print(f'Starting from {before_count} saved bases. Navigate normally in BlueStacks.')
    print(f'Counting every ~{args.segment_seconds}s. Press Ctrl+C to finish.', flush=True)
    command = [args.dumpcap, '-i', str(args.interface),
               '-f', 'tcp port 9929',
               '-b', f'duration:{args.segment_seconds}',
               '-w', str(captures / 'zroute.pcapng')]
    log_path = out / 'dumpcap.log'
    proc = None
    last_activity = time.monotonic()

    def process_closed(include_active=False):
        nonlocal last_activity
        files = sorted(captures.glob('zroute*.pcapng'),
                       key=lambda p: (p.stat().st_mtime_ns, p.name))
        closed = files if include_active else files[:-1]
        for index, file in enumerate(closed):
            if file.name in done or file.stat().st_size < 32:
                continue
            previous = files[index - 1] if index else None
            try:
                process_segment(file, previous, players, views, segments, out, seen_views)
            except (ValueError, OSError, EOFError, IndexError, KeyError) as exc:
                print(f'WARNING: cannot decode {file.name}: {exc}', file=sys.stderr)
                continue
            done.add(file.name)
            last_activity = time.monotonic()

    try:
        with log_path.open('a', encoding='utf-8') as log:
            proc = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=log)
            time.sleep(1)
            if proc.poll() is not None:
                raise RuntimeError(f'dumpcap exited ({proc.returncode}); see {log_path}')
            while proc.poll() is None:
                process_closed()
                if time.monotonic() - last_activity > max(30, args.segment_seconds * 3):
                    print('No completed capture segments yet. '
                          'Check dumpcap.log and whether traffic is reaching the interface.',
                          flush=True)
                    last_activity = time.monotonic()
                time.sleep(1)
            print(f'WARNING: dumpcap ended ({proc.returncode}); see {log_path}',
                  file=sys.stderr)
    except KeyboardInterrupt:
        print('\nStopping; analyzing final capture...', flush=True)
    except OSError as exc:
        raise SystemExit(f'Could not launch dumpcap: {exc}') from exc
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        process_closed(include_active=True)
        print(f'FINAL: {len(players)} observed unique bases '
              f'(+{len(players)-before_count} this session).')
        print('Saved:', out / 'players.csv', out / 'views.csv', out / 'segments.csv')
        print('A unique-base count does not establish full geographic coverage.')


def main():
    parser = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--interface',
                        help='Interface ID reported by dumpcap -D')
    parser.add_argument('--dumpcap', default='dumpcap')
    parser.add_argument('--segment-seconds', type=int, default=15)
    parser.add_argument('--out', type=Path, help='Existing session directory to resume')
    parser.add_argument('--recount', action='store_true',
                        help='Reprocess saved capture segments offline; no new capture')
    watch(parser.parse_args())


if __name__ == '__main__':
    main()
