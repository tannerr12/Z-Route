#!/usr/bin/env python3
"""Count distinct Z-Route bases while manually jumping around the world map.

Requires Wireshark's dumpcap. Captures are passive, and no game-server
requests are generated. Ctrl+C finalizes the current segment and saves CSVs.

Example:
  python network_scan/live_watch.py --interface 1 --dumpcap "C:\\Program Files\\Wireshark\\dumpcap.exe"

"Unique bases" counts decoded distinct player IDs in visited regions; it is
NOT a full-map coverage percentage. Keep PCAPNG and CSV files private.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from scan import BASE_FIELDS, VIEW_FIELDS, inspect, load_csv, save_csv

SEGMENT_FIELDS = ('filename', 'processed_at', 'views', 'observations',
                  'new_bases', 'total_unique', 'decode_failures')


def base_key(player):
    server = str(player.get('server', '')).strip()
    player_id = str(player.get('player_id', '')).strip()
    return (server, player_id) if server and player_id else None


def process_segment(file, players, views, segments, out):
    decoded, errors = inspect(file)
    new, observations = 0, 0
    for view, bases in decoded:
        views.append(view)
        observations += len(bases)
        for player in bases:
            key = base_key(player)
            if key is None:
                continue
            if key not in players:
                new += 1
            players[key] = player
    segments.append(dict(filename=file.name,
                         processed_at=datetime.now(timezone.utc).isoformat(),
                         views=len(decoded), observations=observations,
                         new_bases=new, total_unique=len(players),
                         decode_failures=errors))
    save_csv(out / 'players.csv', BASE_FIELDS,
             sorted(players.values(), key=lambda p: base_key(p) or ('', '')))
    save_csv(out / 'views.csv', VIEW_FIELDS, views)
    save_csv(out / 'segments.csv', SEGMENT_FIELDS, segments)
    centers = {(str(v['center_x']), str(v['center_y'])) for v in views}
    print(f'[{datetime.now().strftime("%H:%M:%S")}] '
          f'{len(decoded)} views | {observations} observations | '
          f'+{new} NEW | {len(players)} UNIQUE TOTAL | '
          f'{len(centers)} map centers | {errors} undecoded', flush=True)


def watch(args):
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
    done = {r['filename'] for r in segments}
    initial = len(players)

    print('Output:', out.resolve())
    print(f'Starting with {initial} saved bases. Jump in BlueStacks as usual.')
    print(f'Updates approximately every {args.segment_seconds} seconds. Ctrl+C to finish.',
          flush=True)
    command = [args.dumpcap, '-i', str(args.interface),
               '-f', 'tcp port 9929',
               '-b', f'duration:{args.segment_seconds}',
               '-w', str(captures / 'zroute.pcapng')]
    log_path = out / 'dumpcap.log'
    proc = None

    def process_closed(include_active=False):
        files = sorted(captures.glob('zroute*.pcapng'),
                       key=lambda p: (p.stat().st_mtime_ns, p.name))
        # Never parse a file dumpcap may still be writing.
        for file in (files if include_active else files[:-1]):
            if file.name in done or file.stat().st_size < 32:
                continue
            try:
                process_segment(file, players, views, segments, out)
            except (ValueError, OSError, EOFError, IndexError, KeyError) as exc:
                print(f'WARNING: {file.name} could not be decoded: {exc}',
                      file=sys.stderr)
                continue
            done.add(file.name)

    try:
        # Log stderr to disk to prevent a full PIPE from stalling overnight capture.
        with log_path.open('a', encoding='utf-8') as log:
            proc = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=log)
            time.sleep(1)
            if proc.poll() is not None:
                raise RuntimeError(f'dumpcap exited (code {proc.returncode}). See {log_path}')
            while proc.poll() is None:
                process_closed()
                time.sleep(1)
            print(f'WARNING: dumpcap ended (code {proc.returncode}). See {log_path}',
                  file=sys.stderr)
    except KeyboardInterrupt:
        print('\nStopping and processing final capture...', flush=True)
    except OSError as exc:
        raise SystemExit(f'Could not start dumpcap: {exc}') from exc
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=4)
        process_closed(include_active=True)
        print(f'FINAL: {len(players)} unique bases observed '
              f'({len(players)-initial} added this run).', flush=True)
        print('Player database:', out / 'players.csv')
        print('View locations:', out / 'views.csv')
        print('Capture segments:', out / 'segments.csv')
        print('Counts represent observed player bases, NOT proven full-map coverage.')


def main():
    parser = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--interface', required=True,
                        help='Network interface identifier from dumpcap -D')
    parser.add_argument('--dumpcap', default='dumpcap',
                        help='Full path to Wireshark dumpcap.exe if not on PATH')
    parser.add_argument('--segment-seconds', type=int, default=8,
                        help='Refresh interval; 3-120 seconds (default 8)')
    parser.add_argument('--out', type=Path,
                        help='Session directory; reuse to continue counting')
    watch(parser.parse_args())


if __name__ == '__main__':
    main()
