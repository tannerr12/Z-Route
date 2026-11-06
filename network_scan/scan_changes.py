#!/usr/bin/env python3
"""Compare two passive Z-Route world-map player snapshots.

Keyed by (server, player_id) instead of username. "Not seen" is never
interpreted as a player disappearing. Moving bases are a first-class result.

Usage:
    python network_scan/scan_changes.py --before network_scans/full_map/players.csv \
      --after network_scans/map_refresh/20261106_140000/players.csv

The inputs are already decoded CSVs, not PCAPs; no ADB or game interaction.\nRenames are the primary output; saved aliases persist in one shared SQLite DB.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from scan import save_csv
from player_history import connection, sync, export_renames

FIELDS=('server','player_id','username_before','username_after',
        'classification','x_before','y_before','x_after','y_after',
        'manhattan_move','alliance_before','alliance_after',
        'level_before','level_after','source_before','source_after')


def read_snapshot(path, server=None):
    """Use one canonical row per stable player ID in each snapshot."""
    if not path.is_file():
        raise ValueError('Missing scan snapshot: '+str(path))
    found={}
    with path.open('r',encoding='utf-8-sig',newline='') as stream:
        reader=csv.DictReader(stream)
        required={'server','player_id','username','x','y'}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError('Not a world-coordinate player CSV: '+str(path))
        for row in reader:
            srv=str(row.get('server') or '').strip()
            pid=str(row.get('player_id') or '').strip()
            if server is not None and srv!=str(server):
                continue
            if not srv or not pid or not str(row.get('username') or '').strip():
                continue
            try:
                x,y=int(row['x']),int(row['y'])
            except (ValueError,TypeError):
                continue
            if not 0<=x<=5000 or not 0<=y<=5000:continue
            key=(srv,pid)
            found[key]=dict(row,x=x,y=y)
    return found


def compare(before, after):
    """Return detailed changes and counts.

    Reappearing IDs must be observed in BOTH snapshots to assert a move.
    An omitted ID only means it was not seen in the later scan.
    """
    changes=[]
    all_keys=set(before)|set(after)
    summary=Counter()
    for server,pid in sorted(all_keys):
        older=before.get((server,pid))
        newer=after.get((server,pid))
        if not older:status='newly_seen'
        elif not newer:status='not_seen_in_after'
        else:
            changes_here=[]
            if (older['x'],older['y'])!=(newer['x'],newer['y']):
                changes_here.append('moved')
            if older.get('username')!=newer.get('username'):
                changes_here.append('renamed')
            if older.get('alliance_tag')!=newer.get('alliance_tag'):
                changes_here.append('alliance_changed')
            if (older.get('base_level') or '')!=(newer.get('base_level') or ''):
                changes_here.append('level_changed')
            status='+'.join(changes_here) if changes_here else 'unchanged'
        summary[status]+=1
        if status=='unchanged':
            continue
        changes.append(dict(
            server=server,player_id=pid,
            username_before=(older or {}).get('username',''),
            username_after=(newer or {}).get('username',''),
            classification=status,
            x_before='' if older is None else older['x'],
            y_before='' if older is None else older['y'],
            x_after='' if newer is None else newer['x'],
            y_after='' if newer is None else newer['y'],
            manhattan_move=(abs(older['x']-newer['x'])+
                            abs(older['y']-newer['y'])
                            if older and newer and status.startswith('moved')
                            else ''),
            alliance_before=(older or {}).get('alliance_tag',''),
            alliance_after=(newer or {}).get('alliance_tag',''),
            level_before=(older or {}).get('base_level',''),
            level_after=(newer or {}).get('base_level',''),
            source_before=(older or {}).get('capture',''),
            source_after=(newer or {}).get('capture','')))
    summary['players_before']=len(before)
    summary['players_after']=len(after)
    summary['observed_in_both']=len(set(before)&set(after))
    summary['names_changed']=sum('renamed' in r['classification'].split('+') for r in changes)
    summary['coordinates_changed']=sum(
        r['classification'].split('+')[0]=='moved' for r in changes)
    return changes,dict(summary)


def run(args):
    before=read_snapshot(args.before,args.server)
    after=read_snapshot(args.after,args.server)
    if not before or not after:
        raise ValueError('Both snapshots must contain at least one valid player.')
    changes,summary=compare(before,after)
    if args.out is None:
        args.out=args.after.parent/'changes_from_previous'
    if (args.out/'changes.csv').resolve() in (args.before.resolve(),args.after.resolve()):
        raise ValueError('Output cannot overwrite an input snapshot.')
    args.out.mkdir(parents=True,exist_ok=True)
    save_csv(args.out/'changes.csv',FIELDS,changes)
    recent_renames=[r for r in changes if 'renamed' in r['classification'].split('+')]
    save_csv(args.out/'renames.csv',FIELDS,recent_renames)
    with connection(args.history_db) as history:
        sync(history,args.network_root,(args.before,args.after))
        lifetime_renames=export_renames(history,args.out/'all_name_changes.csv',args.server)
    summary['lifetime_observed_name_changes']=len(lifetime_renames)
    summary.update(before_source=str(args.before),after_source=str(args.after),
                   compared_at_utc=datetime.now(timezone.utc).isoformat())
    (args.out/'summary.json').write_text(
        json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
    print(f'NAME CHANGES between snapshots: {len(recent_renames):,}')
    print(f'All observed name transitions in persistent history: {len(lifetime_renames):,}')
    print(f'Prior snapshot: {len(before):,} players')
    print(f'New snapshot:   {len(after):,} players')
    print(f'Observed in both: {summary["observed_in_both"]:,}')
    print(f'MOVED coordinates: {summary["coordinates_changed"]:,}')
    print(f'Newly observed: {summary.get("newly_seen",0):,}')
    print(f'Not observed in new scan: {summary.get("not_seen_in_after",0):,} '
          '(NOT proof of departure)')
    print('Saved:',args.out/'renames.csv',args.out/'all_name_changes.csv',
          args.out/'changes.csv',args.out/'summary.json')


def main():
    p=argparse.ArgumentParser(description=__doc__,
                              formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--before',type=Path,required=True)
    p.add_argument('--after',type=Path,required=True)
    p.add_argument('--out',type=Path)
    p.add_argument('--server',type=int,default=125)
    p.add_argument('--network-root',type=Path,default=Path('network_scans'))
    p.add_argument('--history-db',type=Path,default=Path('network_scans/player_history.sqlite3'))
    args=p.parse_args()
    try:run(args)
    except (OSError,ValueError,csv.Error) as exc:p.error(str(exc))


if __name__=='__main__':
    main()
