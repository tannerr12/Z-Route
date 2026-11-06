#!/usr/bin/env python3
"""Publish last recorded EXACT Z-Route world X/Y player coordinates to GitHub Pages.

Inputs come from passively decoded WorldMapViewS2C data, not the old
vision-scanner swipe grid. Run locally after merging network scans:

  python network_scan/compare_player_sessions.py --write-merged network_scans/combined_players.csv
  python network_scan/export_world_map.py

The export is a snapshot, not a live tracker. Shield state is joined by
stable (server, player_id); stale/unobserved shield states are UNKNOWN.
The output under data/ is eligible for GitHub publication: inspect it before
committing, especially if you want to keep your player map private.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path

from scan import save_csv
from shield_state import latest_shield_observations

ROOT = Path('network_scans')
DEFAULT_ROSTER = ROOT / 'combined_players.csv'
DEFAULT_OUT = Path('data/world-players.csv')
WORLD_FIELDS = (
    'server', 'player_id', 'username', 'alliance_tag', 'alliance_name',
    'base_level', 'x', 'y', 'coordinate_source', 'roster_snapshot_at_utc',
    'shield_status', 'recorded_shield_status', 'shield_field_9',
    'shield_observed_at_utc',
)


def safe_integer(raw, *, minimum=0, maximum=5000):
    try:
        value = int(str(raw).strip())
    except (ValueError, TypeError):
        return None
    return value if minimum <= value <= maximum else None


def build_world_roster(rows, server, snapshot_at, shield_observations):
    """Return a last-recorded player map; reject missing or swipe-grid positions."""
    exported = {}
    skipped = 0
    for raw in rows:
        if str(raw.get('server') or '').strip() != str(server):
            continue
        pid = str(raw.get('player_id') or '').strip()
        name = str(raw.get('username') or '').strip()
        x = safe_integer(raw.get('x'))
        y = safe_integer(raw.get('y'))
        level = safe_integer(raw.get('base_level'), minimum=1, maximum=200)
        if not pid or not name or x is None or y is None:
            skipped += 1
            continue
        observed = shield_observations.get((str(server), pid), {})
        exported[pid] = dict(
            server=str(server), player_id=pid, username=name,
            alliance_tag=str(raw.get('alliance_tag') or '').strip(),
            alliance_name=str(raw.get('alliance_name') or '').strip(),
            base_level=level if level is not None else '',
            x=x, y=y, coordinate_source='passive_network_world_xy',
            roster_snapshot_at_utc=snapshot_at,
            shield_status=observed.get('shield_status', 'unknown'),
            recorded_shield_status=observed.get('recorded_shield_status', 'unknown'),
            shield_field_9=observed.get('shield_field_9', ''),
            shield_observed_at_utc=observed.get('shield_observed_at_utc', ''),
        )
    return sorted(exported.values(),
                  key=lambda row: (row['username'].casefold(), row['player_id'])), skipped


def export(args):
    if not args.roster.is_file():
        raise ValueError(
            f'Exact-world player roster not found: {args.roster}. '
            'First run: python network_scan/compare_player_sessions.py '
            '--write-merged network_scans/combined_players.csv')
    with args.roster.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        required = {'server', 'player_id', 'username', 'x', 'y', 'base_level'}
        if not required.issubset(set(reader.fieldnames or ())):
            raise ValueError(
                'Input is not a network world-coordinate roster. '
                'Expected: ' + ', '.join(sorted(required)) +
                '. Do not supply the old data/players.csv swipe-grid export.')
        rows = list(reader)
    if not rows:
        raise ValueError('Input roster has no player records. Refusing empty publication.')
    # Snapshot modification is NOT an exact per-player observation timestamp.
    modified = datetime.fromtimestamp(args.roster.stat().st_mtime,
                                      tz=timezone.utc).isoformat(timespec='seconds')
    shield = ({} if args.no_shields else latest_shield_observations(
        args.network_root, server=args.server,
        max_age_minutes=args.max_shield_age_minutes))
    records, skipped = build_world_roster(rows, args.server, modified, shield)
    if not records:
        raise ValueError(
            f'No valid world coordinates for S{args.server}. '
            'Output unchanged; check your input server and schema.')
    if args.out.resolve() == args.roster.resolve():
        raise ValueError('Output cannot overwrite the source roster.')
    save_csv(args.out, WORLD_FIELDS, records)
    with_level = sum(bool(row['base_level']) for row in records)
    with_shield = sum(row['shield_status'] != 'unknown' for row in records)
    print(f'S{args.server}: exported {len(records):,} last-recorded exact X/Y '
          f'players ({with_level:,} known levels; {with_shield:,} '
          f'recent known shield states); {skipped} invalid same-server rows skipped.')
    print('World coordinate source: passive network scanner; not swipe-grid OCR.')
    print('Roster file modified at:', modified, '(snapshot, not individual sightings)')
    print('Saved:', args.out)
    print('Review and commit this CSV separately if you want it on GitHub Pages.')


def main():
    parser = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--roster', type=Path, default=DEFAULT_ROSTER)
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    parser.add_argument('--network-root', type=Path, default=ROOT)
    parser.add_argument('--server', type=int, default=125)
    parser.add_argument('--max-shield-age-minutes', type=int, default=60,
                        help='Current shield display becomes unknown after this many minutes')
    parser.add_argument('--no-shields', action='store_true')
    args = parser.parse_args()
    if args.max_shield_age_minutes < 0:
        parser.error('--max-shield-age-minutes must be nonnegative')
    try:
        export(args)
    except (OSError, ValueError, csv.Error) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
