#!/usr/bin/env python3
"""Compare passive live-watch and progressive minimap player rosters.

Offline, read-only by default. Does not connect to BlueStacks or game servers.

  python network_scan/compare_player_sessions.py
  python network_scan/compare_player_sessions.py --old network_scans/live/SESSION/players.csv
  python network_scan/compare_player_sessions.py --write-merged network_scans/combined_players.csv

Without --old, the largest valid players.csv in network_scans/live is used.
All counts are deduplicated by (server, player_id), never by player name.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

from scan import BASE_FIELDS, save_csv


def read_players(path):
    people = {}
    if not path.is_file():
        raise ValueError(f'Player CSV not found: {path}')
    with path.open('r', newline='', encoding='utf-8-sig') as source:
        reader = csv.DictReader(source)
        if not {'server', 'player_id'}.issubset(set(reader.fieldnames or [])):
            raise ValueError(f'CSV must contain server and player_id: {path}')
        for person in reader:
            server = str(person.get('server') or '').strip()
            pid = str(person.get('player_id') or '').strip()
            if not server or not pid:
                continue
            people[(server, pid)] = person
    return people


def locate_baseline(root):
    candidates = []
    for path in (root / 'live').glob('*/players.csv'):
        try:
            people = read_players(path)
        except (OSError, ValueError, csv.Error):
            continue
        if people:
            candidates.append((len(people), path))
    if not candidates:
        raise ValueError('No nonempty live-watch players.csv found under '
                         + str(root / 'live'))
    candidates.sort(key=lambda value: (value[0], str(value[1])), reverse=True)
    return candidates[0][1]


def compare(old, new, goal):
    old_ids, new_ids = set(old), set(new)
    both = old_ids & new_ids
    old_only = old_ids - new_ids
    new_only = new_ids - old_ids
    union = old_ids | new_ids
    print('Previous live-watch IDs :', f'{len(old):,}')
    print('New full-map scan IDs  :', f'{len(new):,}')
    print('IDs in both sessions   :', f'{len(both):,}')
    print('Only in previous scan  :', f'{len(old_only):,}')
    print('Only in new scan       :', f'{len(new_only):,}')
    print('Union of unique IDs    :', f'{len(union):,}')
    print('Target (~' + f'{goal:,}' + ')       :', 
          f'{100*len(union)/goal:.1f}% of target')
    if old_ids:
        print('Current scan recaptures:', f'{100*len(both)/len(new_ids):.1f}%'
              if new_ids else 'n/a', 'of new scan IDs')
    print('This compares distinct observed IDs, not geographic completeness.')
    return {'both': both, 'old_only': old_only, 'new_only': new_only,
            'union': union}


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--old', type=Path,
                        help='Prior live-watch players.csv (default: largest live session)')
    parser.add_argument('--new', type=Path,
                        default=Path('network_scans/full_map/players.csv'),
                        help='Current full-map players.csv')
    parser.add_argument('--live-root', type=Path, default=Path('network_scans'))
    parser.add_argument('--goal', type=int, default=9500)
    parser.add_argument('--write-merged', type=Path,
                        help='Optional private output CSV; never overwrites original scans')
    args = parser.parse_args()
    if args.goal < 1:
        raise SystemExit('--goal must be positive')
    try:
        old_path = args.old or locate_baseline(args.live_root)
        old = read_players(old_path)
        new = read_players(args.new)
    except (OSError, ValueError, csv.Error) as exc:
        raise SystemExit(str(exc)) from exc
    print('Comparison baseline:', old_path)
    print('New scan:', args.new)
    compare(old, new, args.goal)
    if args.write_merged is not None:
        out = args.write_merged
        if out.resolve() in (old_path.resolve(), args.new.resolve()):
            raise SystemExit('Merged output must not overwrite input rosters.')
        merged = dict(old)
        merged.update(new)
        save_csv(out, BASE_FIELDS,
                 sorted(merged.values(), key=lambda p: (
                     str(p.get('server', '')), str(p.get('player_id', '')))))
        print('Saved merged roster:', out)


if __name__ == '__main__':
    main()
