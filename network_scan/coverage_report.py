#!/usr/bin/env python3
"""Private, local Z-Route coverage, player directory and name-history dashboard.

No BlueStacks/game-server requests or public uploads are made.
    python network_scan/coverage_report.py
    python network_scan/coverage_report.py --grid 30
    python network_scan/coverage_report.py --no-sync
"""
from __future__ import annotations
import argparse
import csv
import json
import math
from collections import Counter
from pathlib import Path

from compare_player_sessions import locate_baseline
from player_history import connection, directory, sync
from scan import save_csv

CELL_FIELDS = ('row','col','x_min','x_max','y_min','y_max','player_count',
               'prior_only','shared','new_only','other','view_centers_in_cell',
               'nearest_center_distance')
REVIEW_FIELDS = ('rank','center_x','center_y','row','col','player_count',
                 'nearest_center_distance','reason')
FAIL_FIELDS = ('target_id','stage','tap_x','tap_y','status','attempts')


def as_int(value, default=None):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def read_roster(path, server):
    if not path.is_file():
        raise ValueError('Missing '+str(path)+'; run compare_player_sessions.py --write-merged network_scans/combined_players.csv')
    found, skipped = {}, Counter()
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if not {'server','player_id','x','y','username'}.issubset(reader.fieldnames or ()):
            raise ValueError('Roster needs server, player_id, x, y, username')
        for row in reader:
            if as_int(row.get('server')) != server:
                skipped['other_server'] += 1
                continue
            pid = str(row.get('player_id') or '').strip()
            x, y = as_int(row.get('x')), as_int(row.get('y'))
            if not pid or x is None or y is None or not (0 <= x <= 5000 and 0 <= y <= 5000):
                skipped['invalid'] += 1
                continue
            key = f'{server}:{pid}'
            found[key] = dict(id=key, server=str(server), player_id=pid,
                username=str(row.get('username') or ''), x=x, y=y,
                alliance_tag=str(row.get('alliance_tag') or ''),
                alliance_name=str(row.get('alliance_name') or ''),
                level=str(row.get('base_level') or ''))
    return found, skipped


def read_id_set(path, server):
    if path is None or not path.is_file():
        return None
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if not {'server','player_id'}.issubset(reader.fieldnames or ()):
            return None
        return {f'{server}:{str(r["player_id"]).strip()}' for r in reader
                if as_int(r.get('server')) == server and r.get('player_id')}


def read_view_centers(views_csv, checkpoint_json):
    evidence = {}
    if views_csv is not None and views_csv.is_file():
        with views_csv.open(encoding='utf-8-sig', newline='') as stream:
            for row in csv.DictReader(stream):
                x, y = as_int(row.get('center_x')), as_int(row.get('center_y'))
                if x is not None and y is not None and 0 <= x <= 5000 and 0 <= y <= 5000:
                    evidence.setdefault((x, y), set()).add('live')
    failed = []
    if checkpoint_json is not None and checkpoint_json.is_file():
        doc = json.loads(checkpoint_json.read_text(encoding='utf-8'))
        by_id = {str(p.get('target_id')):p for p in doc.get('entries', [])}
        for p in by_id.values():
            for pair in p.get('centers', []):
                if not isinstance(pair,(list,tuple)) or len(pair)<2:
                    continue
                x,y = as_int(pair[0]), as_int(pair[1])
                if x is not None and y is not None and 0 <= x <= 5000 and 0 <= y <= 5000:
                    evidence.setdefault((x,y),set()).add('grid')
            if p.get('status') not in ('OK','OVERLAP','EMPTY'):
                failed.append({k:p.get(k,'') for k in FAIL_FIELDS})
    centers = [dict(x=x,y=y,source='both' if len(sources)==2 else next(iter(sources)))
               for (x,y),sources in sorted(evidence.items())]
    return centers,failed


def bounds_for(players, centers, explicit):
    if explicit:
        a,b,c,d=explicit
        if a>=c or b>=d:
            raise ValueError('Invalid world bounds: xmin ymin xmax ymax')
        return list(explicit),'explicit bounds'
    xs=[p['x'] for p in players.values()]+[c['x'] for c in centers]
    ys=[p['y'] for p in players.values()]+[c['y'] for c in centers]
    if not xs or not ys:
        raise ValueError('No world coordinate observations available')
    dx=max(1,max(xs)-min(xs));dy=max(1,max(ys)-min(ys))
    padx=max(10,math.ceil(dx*.025));pady=max(10,math.ceil(dy*.025))
    return [max(0,min(xs)-padx),max(0,min(ys)-pady),max(xs)+padx,max(ys)+pady], 'observed extent + margin'


def index(x,y,bounds,grid):
    xmin,ymin,xmax,ymax=bounds
    if not xmin<=x<=xmax or not ymin<=y<=ymax:
        return None
    col=min(grid-1,int((x-xmin)/(xmax-xmin)*grid))
    row=min(grid-1,int((y-ymin)/(ymax-ymin)*grid))
    return row*grid+col


def bin_data(players, old, new, centers, bounds, grid, top):
    xmin,ymin,xmax,ymax=bounds
    cells=[]
    for row in range(grid):
        for col in range(grid):
            cells.append(dict(row=row,col=col,
                x_min=round(xmin+(xmax-xmin)*col/grid,2),
                x_max=round(xmin+(xmax-xmin)*(col+1)/grid,2),
                y_min=round(ymin+(ymax-ymin)*row/grid,2),
                y_max=round(ymin+(ymax-ymin)*(row+1)/grid,2),
                player_count=0,prior_only=0,shared=0,new_only=0,other=0,
                view_centers_in_cell=0,nearest_center_distance=''))
    outside=0
    for pid,p in players.items():
        idx=index(p['x'],p['y'],bounds,grid)
        if idx is None:
            outside+=1
            continue
        cell=cells[idx];cell['player_count']+=1
        if old is None or new is None: cell['other']+=1
        elif pid in old and pid in new: cell['shared']+=1
        elif pid in old: cell['prior_only']+=1
        elif pid in new: cell['new_only']+=1
        else: cell['other']+=1
    for center in centers:
        idx=index(center['x'],center['y'],bounds,grid)
        if idx is not None: cells[idx]['view_centers_in_cell']+=1
    for cell in cells:
        midpoint=((cell['x_min']+cell['x_max'])/2,(cell['y_min']+cell['y_max'])/2)
        if centers:
            cell['nearest_center_distance']=round(min(math.hypot(midpoint[0]-p['x'],midpoint[1]-p['y']) for p in centers),1)
    candidates=[]
    if centers:
        ordered=sorted((c for c in cells if c['view_centers_in_cell']==0),
            key=lambda c:(-c['nearest_center_distance'],c['player_count'],c['row'],c['col']))
        for rank,c in enumerate(ordered[:top],1):
            candidates.append(dict(rank=rank,row=c['row'],col=c['col'],
                center_x=round((c['x_min']+c['x_max'])/2,1),
                center_y=round((c['y_min']+c['y_max'])/2,1),
                player_count=c['player_count'],
                nearest_center_distance=c['nearest_center_distance'],
                reason='Far from recorded map-view centers, not confirmed unscanned'))
    return cells,candidates,outside


def build(args):
    roster, skipped=read_roster(args.players,args.server)
    if not roster:
        raise ValueError(f'No usable player records on server {args.server}')
    old_path=args.old
    if old_path is None:
        try:old_path=locate_baseline(args.network_root)
        except ValueError:old_path=None
    new_path=args.new or args.network_root/'full_map'/'players.csv'
    old,new=read_id_set(old_path,args.server),read_id_set(new_path,args.server)
    views=args.views or (old_path.parent/'views.csv' if old_path else None)
    checkpoint=args.checkpoint or args.network_root/'full_map'/'checkpoint.json'
    centers,failed=read_view_centers(views,checkpoint)
    bounds,bounds_type=bounds_for(roster,centers,args.bounds)
    cells,candidates,outside=bin_data(roster,old,new,centers,bounds,args.grid,args.top)

    with connection(args.history_db) as db:
        if not args.no_sync:
            sync(db,args.network_root,args.history_file)
        histories={f'{p["server"]}:{p["player_id"]}':p for p in directory(db,args.server)}
    players=[]
    for pid,p in roster.items():
        h=histories.get(pid)
        players.append(dict(p,aliases=(h['aliases'] if h else [p['username']]),
            name_events=(h['name_events'] if h else []),
            observed_name_changes=(h['observed_name_changes'] if h else 0),
            history_snapshot_count=(h['snapshot_count'] if h else 0),
            last_seen=(h['last_seen'] if h else ''),
            time_basis=(h['time_basis'] if h else 'no saved snapshots')))
    players.sort(key=lambda p:(p['username'].casefold(),p['player_id']))
    tallies={name:sum(c[name] for c in cells)
             for name in ('player_count','prior_only','shared','new_only','other')}
    summary=dict(server=args.server,unique_ids=len(roster),plotted=tallies['player_count'],
        outside_bounds=outside,invalid_rows=skipped['invalid'],bounds=bounds,
        bounds_type=bounds_type,grid=args.grid,
        cells_with_players=sum(c['player_count']>0 for c in cells),
        distinct_view_centers=len(centers),failed_targets=len(failed),
        prior_only=tallies['prior_only'],shared=tallies['shared'],
        new_only=tallies['new_only'],unclassified=tallies['other'],
        source_comparison_available=old is not None and new is not None,
        historical_snapshots=sum(p['history_snapshot_count'] for p in players),
        players_with_observed_renames=sum(bool(p['observed_name_changes']) for p in players),
        note=('View centers are sample points, not proven view footprints. '
              'An observed alias is not the exact time a player renamed.'))
    payload=dict(summary=summary,cells=cells,centers=centers,candidates=candidates,
                 failed_targets=failed,players=players)

    args.out.mkdir(parents=True,exist_ok=True)
    save_csv(args.out/'coverage_cells.csv',CELL_FIELDS,cells)
    save_csv(args.out/'review_candidates.csv',REVIEW_FIELDS,candidates)
    save_csv(args.out/'failed_minimap_targets.csv',FAIL_FIELDS,failed)
    (args.out/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    template=Path(__file__).with_name('coverage_template.html').read_text(encoding='utf-8')
    marker='__REPORT_DATA__'
    if marker not in template:
        raise ValueError('Missing data marker in coverage_template.html')
    embedded=json.dumps(payload,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c')
    destination=args.out/'coverage.html'
    destination.write_text(template.replace(marker,embedded),encoding='utf-8')
    print(f'Coverage report: S{args.server} — {len(roster):,} stable player IDs; '
          f'{summary["players_with_observed_renames"]} players with observed rename events')
    print(f'{len(centers)} distinct map-view centers, {len(failed)} review targets, '
          f'{len(candidates)} sampling-priority suggestions')
    print('No viewport-completeness claims: map centers are samples.')
    print('Open this PRIVATE local file:',destination.resolve())
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--players',type=Path,default=Path('network_scans/combined_players.csv'))
    parser.add_argument('--network-root',type=Path,default=Path('network_scans'))
    parser.add_argument('--old',type=Path)
    parser.add_argument('--new',type=Path)
    parser.add_argument('--views',type=Path)
    parser.add_argument('--checkpoint',type=Path)
    parser.add_argument('--history-db',type=Path,default=Path('network_scans/player_history.sqlite3'))
    parser.add_argument('--history-file',type=Path,action='append',default=[],
                        help='Extra historical player CSV; repeatable')
    parser.add_argument('--no-sync',action='store_true',
                        help='Do not import source CSV snapshots before rendering')
    parser.add_argument('--bounds',type=int,nargs=4,metavar=('XMIN','YMIN','XMAX','YMAX'))
    parser.add_argument('--server',type=int,default=125)
    parser.add_argument('--grid',type=int,default=24)
    parser.add_argument('--top',type=int,default=25)
    parser.add_argument('--out',type=Path,default=Path('network_scans/coverage'))
    args=parser.parse_args()
    if not 6<=args.grid<=60 or not 1<=args.top<=100:
        parser.error('--grid must be 6..60 and --top 1..100')
    try:build(args)
    except (OSError,ValueError,csv.Error,json.JSONDecodeError) as exc:
        parser.error(str(exc))


if __name__=='__main__':
    main()
