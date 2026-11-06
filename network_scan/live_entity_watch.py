#!/usr/bin/env python3
"""Passive live world-map entity watcher for Z-Route.

Manual BlueStacks navigation only. No ADB clicks or direct server requests.
Show newly observed non-player entities and query their last seen X/Y.

Examples (repo root):
  python network_scan/live_entity_watch.py watch --interface Wi-Fi --dumpcap "C:\Program Files\Wireshark\dumpcap.exe"
  python network_scan/live_entity_watch.py near --x 500 --y 450 --radius 8
  python network_scan/live_entity_watch.py match --x 500 --y 450 --label Walker --screenshot "evidence.png"
  python network_scan/live_entity_watch.py replay --captures some_capture.pcapng
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from live_watch import resolve_interface, traffic_stats
from map_entity_probe import parse_object, classify, status_record, load_labels
from scan import save_csv
from zroute_map_decoder import (application_messages, decode_payload,
                                map_root, protobuf_fields)

ROOT = Path('network_scans') / 'entity_live'
LATEST_FIELDS = ('entity_key','server','x','y','type_code','type_label','classification',
                 'subtype','candidate_group_id','candidate_group_ambiguous',
                 'first_seen_utc','last_seen_utc','last_capture',
                 'sightings','last_detail_scalars','last_detail_text')
EVENT_FIELDS = ('seen_at_utc','segment','view_index','server','x','y',
                'type_code','type_label','classification','subtype',
                'candidate_group_id','candidate_group_ambiguous','entity_key')
STATUS_FIELDS = ('seen_at_utc','capture','server','player_id','username','x','y',
                 'shield_status','status_9','status_13','status_15','status_18',
                 'status_18_utc','status_23','raw_extra_scalars_json')
SEG_FIELDS = ('file','observed_at_utc','incoming_packets','incoming_bytes',
              'decoded_views','new_entity_positions','sightings',
              'distinct_types','ambiguous_id_groups','player_status_records',
              'errors','status')
MATCH_FIELDS = ('matched_at_utc','server','x','y','type_code','subtype',
                'candidate_group_id','entity_key','label','screenshot',
                'last_seen_utc','verification_note')
TYPE_FIELDS = ('type_code','type_label','classification',
               'distinct_positions','sightings')


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def entity_key(obj):
    """Location-level observation key; NOT a proven stable moving object ID."""
    basis = (obj['server'],obj['type_code'],obj['x'],obj['y'],
             obj['subtype'],obj['raw_object_field1'])
    return hashlib.sha256(repr(basis).encode('utf-8')).hexdigest()[:24]


def candidate_key(obj):
    group=obj.get('raw_object_field1')
    if group is None or group == 0:
        return None
    # Candidate groups can contain multiple simultaneous entities.
    return (obj['server'],obj['type_code'],str(group))


def iter_entities(path):
    """Yield verified full-map responses, their entities and player statuses.

    WorldMapViewUpdateS2C uses an unknown schema; do not silently treat it
    as a full snapshot or use absence as despawn evidence.
    """
    for name, when, raw in application_messages(path):
        if name!='WorldMapViewS2C':
            yield 'update_skipped',None,None,None
            continue
        try:
            decoded,_=decode_payload(raw)
            root=map_root(decoded)
            nonplayers=[]
            statuses=[]
            for field,wire,blob in root:
                if field!=5 or wire!=2:
                    continue
                try:
                    obj=parse_object(blob)
                except (ValueError,TypeError,UnicodeDecodeError):
                    continue
                if obj is None:
                    continue
                if obj['type_code']==1:
                    statuses.append(obj)
                else:
                    nonplayers.append(obj)
            yield 'view',nonplayers,statuses,hashlib.sha256(raw).hexdigest()
        except (ValueError,TypeError,EOFError,OSError) as exc:
            yield 'decode_error',str(exc),None,None


def observation_time(file):
    """Timestamp reflects capture-file closure, not exact in-game spawn time."""
    return datetime.fromtimestamp(file.stat().st_mtime,
                                  timezone.utc).isoformat(timespec='seconds')


def append_csv(path,headers,rows):
    if not rows:return
    path.parent.mkdir(parents=True,exist_ok=True)
    exists=path.is_file() and path.stat().st_size>0
    with path.open('a',encoding='utf-8-sig' if not exists else 'utf-8',
                   newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=headers,extrasaction='ignore')
        if not exists:writer.writeheader()
        writer.writerows(rows)


def read_csv(path):
    if not path.is_file():return []
    with path.open('r',newline='',encoding='utf-8-sig') as handle:
        return list(csv.DictReader(handle))


def prepare_state(out):
    latest={item['entity_key']:item for item in read_csv(out/'latest_entities.csv')}
    segments=read_csv(out/'segments.csv')
    processed={r['file'] for r in segments}
    return latest,segments,processed


def process(file,previous,out,latest,segments,labels,cache,
            focus,limit=8, index=0):
    # Overlapping windows repair TCP messages spanning capture rotations.
    temporary=out/'.joined_entity_window.pcapng'
    if previous:
        try:
            with temporary.open('wb') as dest:
                for source in (previous,file):
                    with source.open('rb') as input_stream:
                        shutil.copyfileobj(input_stream,dest)
            to_parse=temporary
        except OSError:
            temporary.unlink(missing_ok=True)
            raise
    else:
        to_parse=file
    # Approximate time of capture file closure.
    when=observation_time(file)
    views=0
    errors=0
    update_skipped=0
    ambiguous=0
    new_positions=0
    total_sightings=0
    type_count=Counter()
    rows=[]
    player_rows=[]
    examples=[]
    try:
        for kind,nonplayers,statuses,fingerprint in iter_entities(to_parse):
            if kind=='update_skipped':
                update_skipped+=1;continue
            if kind=='decode_error':
                errors+=1;continue
            # Message fingerprint only de-duplicates duplicate responses in
            # adjacent, overlapping capture windows. A later identical view
            # can still be an independent sighting.
            last=cache.get(fingerprint)
            if last is not None and index-last<=1:
                continue
            cache[fingerprint]=index
            views+=1
            grouped=defaultdict(set)
            for obj in nonplayers:
                group=candidate_key(obj)
                if group is not None:
                    grouped[group].add((obj['x'],obj['y']))
            ambiguous_groups={k for k,positions in grouped.items() if len(positions)>1}
            ambiguous+=len(ambiguous_groups)
            # Only one row per visible entity per view.
            within_view=set()
            for obj in nonplayers:
                key=entity_key(obj)
                if key in within_view:continue
                within_view.add(key)
                code=obj['type_code']
                name,classification=classify(code,labels)
                group=candidate_key(obj)
                is_ambiguous=group in ambiguous_groups
                current=latest.get(key)
                record=dict(
                    entity_key=key,server=obj['server'],x=obj['x'],y=obj['y'],
                    type_code=code,type_label=name,classification=classification,
                    subtype='' if obj['subtype'] is None else obj['subtype'],
                    candidate_group_id='' if group is None else group[-1],
                    candidate_group_ambiguous=str(bool(is_ambiguous)).lower(),
                    first_seen_utc=current['first_seen_utc'] if current else when,
                    last_seen_utc=when,last_capture=file.name,
                    sightings=int(current.get('sightings') or 0)+1 if current else 1,
                    last_detail_scalars=json.dumps(obj['detail_scalars'],
                                                  separators=(',',':'),ensure_ascii=False),
                    last_detail_text=json.dumps(obj['detail_text'],
                                               separators=(',',':'),ensure_ascii=False))
                latest[key]=record
                rows.append(dict(seen_at_utc=when,segment=file.name,
                                 view_index=views,**{
                    col:record.get(col,'') for col in EVENT_FIELDS
                    if col not in ('seen_at_utc','segment','view_index')}))
                type_count[code]+=1
                total_sightings+=1
                if not current:
                    new_positions+=1
                    if focus is None or code in focus:
                        examples.append(record)
            for player in statuses:
                if player.get('player_id') is None:continue
                info=status_record(player,file.name,when)
                player_rows.append(dict(seen_at_utc=when,**info))
    finally:
        if previous:temporary.unlink(missing_ok=True)
    append_csv(out/'entity_sightings.csv',EVENT_FIELDS,rows)
    append_csv(out/'player_status_sightings.csv',STATUS_FIELDS,player_rows)
    save_csv(out/'latest_entities.csv',LATEST_FIELDS,
             sorted(latest.values(),key=lambda p:(
                 str(p['server']),int(p['type_code']),int(p['x']),int(p['y']))))
    tally=Counter(str(p['type_code']) for p in latest.values())
    save_csv(out/'type_summary.csv',TYPE_FIELDS,
             [dict(type_code=code,
                   type_label=classify(int(code),labels)[0],
                   classification=classify(int(code),labels)[1],
                   distinct_positions=count,
                   sightings=sum(int(p['sightings']) for p in latest.values()
                                if str(p['type_code'])==code))
              for code,count in tally.most_common()])
    stats=traffic_stats(file)
    status=('NO_GAME_TRAFFIC' if stats['incoming_packets']==0 else
            'NO_DECODABLE_MAP_VIEW' if views==0 else 'MAP_VIEWS_DECODED')
    seg=dict(file=file.name,observed_at_utc=when,
             incoming_packets=stats['incoming_packets'],
             incoming_bytes=stats['incoming_bytes'],
             decoded_views=views,new_entity_positions=new_positions,
             sightings=total_sightings,distinct_types=len(type_count),
             ambiguous_id_groups=ambiguous,
             player_status_records=len(player_rows),
             errors=errors,status=status)
    segments.append(seg)
    append_csv(out/'segments.csv',SEG_FIELDS,[seg])
    timestr=datetime.fromisoformat(when).strftime('%H:%M:%S UTC')
    print(f'[{timestr}] {file.name} | {views} map views | '
          f'+{new_positions} new entity positions | '
          f'{len(latest)} stored positions | '
          f'{total_sightings} sightings | '
          f'{ambiguous} shared-ID groups | {status}',flush=True)
    if examples:
        def sort_key(p):
            return (0 if p['type_code'] in (3,5,6) else 1,
                    -int(p['sightings']),int(p['type_code']))
        for p in sorted(examples,key=sort_key)[:limit]:
            print(f'  S{p["server"]} X:{p["x"]} Y:{p["y"]} '
                  f'type:{p["type_code"]} subtype:{p["subtype"]} '
                  f'candidate-group:{p["candidate_group_id"] or "none"}',
                  flush=True)
        if len(examples)>limit:
            print(f'  ... {len(examples)-limit} more new positions; use near for details',
                  flush=True)
    return seg


def decode_windows(paths,out,labels,focus,limit=8,fingerprint_cache=None):
    out.mkdir(parents=True,exist_ok=True)
    latest,segments,done=prepare_state(out)
    # Recent fingerprint cache only; old repeats count as fresh observations.
    if fingerprint_cache is None:
        fingerprint_cache={}
    previous=None
    for index,file in enumerate(paths):
        if file.name not in done and file.stat().st_size>40:
            process(file,previous,out,latest,segments,labels,fingerprint_cache,
                    focus,limit,index)
            done.add(file.name)
        previous=file
    return latest,segments


def watch(args):
    device=resolve_interface(args.dumpcap,args.interface)
    out=args.out or ROOT / datetime.now().strftime('%Y%m%d_%H%M%S')
    out.mkdir(parents=True,exist_ok=True)
    captures=out/'captures'
    captures.mkdir(exist_ok=True)
    print('Private session:',out.resolve())
    print('Navigate manually and keep Z-Route world map open.')
    print('Each closed capture window is analyzed; moving entities can be stale.')
    print('To check nearby objects, run near in a SECOND PowerShell window.')
    print('Ctrl+C ends capture and flushes the final segment.',flush=True)
    cmd=[args.dumpcap,'-i',device,'-f','tcp port 9929',
         '-b',f'duration:{args.segment_seconds}',
         '-w',str(captures/'entity.pcapng')]
    with (out/'dumpcap.log').open('a',encoding='utf-8') as log:
        proc=subprocess.Popen(cmd,stdout=subprocess.DEVNULL,stderr=log)
        try:
            time.sleep(.7)
            if proc.poll() is not None:
                raise RuntimeError('dumpcap exited early; inspect '+str(out/'dumpcap.log'))
            last_warning=0
            fingerprint_cache={}
            while proc.poll() is None:
                files=sorted(captures.glob('entity*.pcapng'),
                             key=lambda p:(p.stat().st_mtime_ns,p.name))
                if len(files)>1:
                    decode_windows(files[:-1],out,args.labels,args.types,args.print_limit,
                                   fingerprint_cache=fingerprint_cache)
                elif time.monotonic()-last_warning>max(20,args.segment_seconds*3):
                    # A new dumpcap file often appears only after traffic arrives.
                    print('Waiting for first completed capture window; '
                          'move to a different world-map region.',flush=True)
                    last_warning=time.monotonic()
                time.sleep(.8)
            raise RuntimeError(f'dumpcap stopped unexpectedly ({proc.returncode}); inspect dumpcap.log')
        except KeyboardInterrupt:
            print('\nStopping live capture...',flush=True)
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:proc.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    proc.kill();proc.wait(timeout=5)
            files=sorted(captures.glob('entity*.pcapng'),
                         key=lambda p:(p.stat().st_mtime_ns,p.name))
            if files:
                decode_windows(files,out,args.labels,args.types,args.print_limit,
                               fingerprint_cache=fingerprint_cache)
    print('Final data:',out.resolve())
    print('REMINDER: no missing sighting establishes despawn or a confirmed move.')


def latest_session(root):
    sessions=sorted((p for p in root.glob('*') if p.is_dir() and
                     (p/'latest_entities.csv').is_file()),
                    key=lambda p:p.stat().st_mtime,reverse=True)
    if not sessions:
        raise SystemExit('No live entity sessions. Run watch or replay first.')
    return sessions[0]


def nearby(args):
    out=args.session or latest_session(ROOT)
    rows=read_csv(out/'latest_entities.csv')
    if not rows:
        raise SystemExit('No entity records in '+str(out))
    now_time=datetime.now(timezone.utc)
    matches=[]
    for item in rows:
        if args.server is not None and int(item['server'])!=args.server:
            continue
        code=int(item['type_code'])
        if args.types is not None and code not in args.types:
            continue
        distance=math.hypot(int(item['x'])-args.x,int(item['y'])-args.y)
        if distance>args.radius:continue
        try:
            seen=datetime.fromisoformat(item['last_seen_utc'])
        except (ValueError,TypeError):
            continue
        age=(now_time-seen).total_seconds()/60
        if args.within_minutes is not None and (age<0 or age>args.within_minutes):
            continue
        matches.append((distance,age,item))
    matches.sort(key=lambda x:(x[0],x[1]))
    print(f'Near S{args.server or "ANY"} X:{args.x} Y:{args.y}, '
          f'radius {args.radius} — {len(matches)} candidates '
          f'from {out} (age from last saved capture):')
    for dist,age,p in matches[:args.limit]:
        print(f'  X:{p["x"]} Y:{p["y"]} '
              f'type:{p["type_code"]} subtype:{p["subtype"]} '
              f'group:{p["candidate_group_id"] or "none"} '
              f'last seen {age:.1f} min ago; '
              f'{p["sightings"]} sightings; distance {dist:.1f}')
    if not matches:print('No recent matching entities. Jump near the target while watch is running.')
    return matches



def trail(args):
    """Show all observed positions in a candidate ID group, not a proven path."""
    out=args.session or latest_session(ROOT)
    events=read_csv(out/'entity_sightings.csv')
    if not events:
        raise SystemExit('No saved sightings under '+str(out))
    if not args.group_id:
        raise SystemExit('Use --group-id from a near result.')
    matches=[row for row in events
             if str(row.get('server'))==str(args.server)
             and str(row.get('type_code'))==str(args.code)
             and str(row.get('candidate_group_id'))==str(args.group_id)]
    matches.sort(key=lambda p:(p['seen_at_utc'],p['segment'],
                                int(p['view_index'])))
    selected=matches[-args.limit:]
    print(f'Candidate group S{args.server} type:{args.code} ID:{args.group_id}')
    print(f'Found {len(matches)} sightings in {out}. '
          'A candidate ID is NOT guaranteed to identify one moving object.')
    for row in selected:
        print(f'  {row["seen_at_utc"]} '
              f'S{row["server"]} X:{row["x"]} Y:{row["y"]} '
              f'subtype:{row["subtype"]} '
              f'shared-in-view:{row["candidate_group_ambiguous"]} '
              f'({row["segment"]}, view {row["view_index"]})')
    if not matches:
        print('No matching sightings. Use near first and copy the candidate-group ID.')
    elif any(r['candidate_group_ambiguous']=='true' for r in matches):
        print('WARNING: this ID was associated with multiple positions in a '
              'single view. It cannot be used as a unique movement path.')
    else:
        print('Positions may reflect different sightings, but true movement '
              'still requires visual confirmation and reliable object identity.')



def match(args):
    if not args.label.strip():
        raise SystemExit('Visual label cannot be blank.')
    if args.screenshot and not args.screenshot.is_file():
        raise SystemExit('Screenshot file not found: '+str(args.screenshot))
    if args.server is None:
        raise SystemExit('Use --server with match so we do not confuse servers.')
    found=nearby(args)
    if args.code is not None:
        found=[result for result in found if int(result[2]['type_code'])==args.code]
    if not found:
        raise SystemExit('No matching nearby candidate. Capture the map first, '
                         'then use near or increase --radius.')
    if len(found)!=1:
        print('AMBIGUOUS: Multiple entities match. Use --code and --radius 0 '
              'or an exact X/Y. No label saved.')
        raise SystemExit(2)
    distance,age,p=found[0]
    if distance>0 and not args.allow_nearby:
        raise SystemExit('Closest entity is not at the exact requested X/Y. '
                         'Use --allow-nearby only after visually confirming.')
    out=args.session or latest_session(ROOT)
    row=dict(matched_at_utc=now(),server=p['server'],x=p['x'],y=p['y'],
             type_code=p['type_code'],subtype=p['subtype'],
             candidate_group_id=p['candidate_group_id'],
             entity_key=p['entity_key'],label=args.label.strip(),
             screenshot=str(args.screenshot) if args.screenshot else '',
             last_seen_utc=p['last_seen_utc'],
             verification_note='User-reported visual match; not a global type classification')
    append_csv(out/'visual_matches.csv',MATCH_FIELDS,[row])
    print(f'VISUAL MATCH SAVED: {args.label} at S{p["server"]} '
          f'X:{p["x"]} Y:{p["y"]} type:{p["type_code"]} '
          f'subtype:{p["subtype"]}. This labels only this specific sighting.')
    print('Saved:',out/'visual_matches.csv')


def types_arg(s):
    if s is None:return None
    try:return {int(v.strip()) for v in s.split(',') if v.strip()}
    except ValueError as exc:raise argparse.ArgumentTypeError('Types must be comma-separated integers') from exc


def main():
    parser=argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    commands=parser.add_subparsers(dest='command',required=True)

    w=commands.add_parser('watch',help='Live Wireshark rotating capture (manual navigation)')
    w.add_argument('--interface',default='Wi-Fi')
    w.add_argument('--dumpcap',default='dumpcap')
    w.add_argument('--segment-seconds',type=int,default=5)
    w.add_argument('--out',type=Path)
    w.add_argument('--types',type=types_arg,help='Only PRINT these type codes (capture all)')
    w.add_argument('--labels',type=Path,help='Optional existing labels JSON')
    w.add_argument('--print-limit',type=int,default=8)
    w.set_defaults(fn=watch)

    replay=commands.add_parser('replay',help='Analyze existing captures with no new capture')
    replay.add_argument('--captures',nargs='+',type=Path,required=True)
    replay.add_argument('--out',type=Path,default=ROOT/'offline_replay')
    replay.add_argument('--types',type=types_arg)
    replay.add_argument('--labels',type=Path)
    replay.add_argument('--print-limit',type=int,default=8)
    replay.set_defaults(fn=lambda a:decode_windows(
        a.captures,a.out,load_labels(a.labels),a.types,a.print_limit))

    for name in ('near','match'):
        cmd=commands.add_parser(name,help='Find currently observed entities near X/Y'
                                if name=='near' else 'Mark an exact visually confirmed object')
        cmd.add_argument('--session',type=Path,help='Specific live session folder')
        cmd.add_argument('--server',type=int,default=125)
        cmd.add_argument('--x',type=int,required=True)
        cmd.add_argument('--y',type=int,required=True)
        cmd.add_argument('--radius',type=float,default=5 if name=='near' else 0)
        cmd.add_argument('--types',type=types_arg)
        cmd.add_argument('--within-minutes',type=float,default=10)
        cmd.add_argument('--limit',type=int,default=30)
        if name=='match':
            cmd.add_argument('--label',required=True)
            cmd.add_argument('--code',type=int)
            cmd.add_argument('--screenshot',type=Path)
            cmd.add_argument('--allow-nearby',action='store_true')
        cmd.set_defaults(fn=nearby if name=='near' else match)
    trail_cmd=commands.add_parser('trail',help='Review recent positions for a candidate entity ID')
    trail_cmd.add_argument('--session',type=Path)
    trail_cmd.add_argument('--server',type=int,default=125)
    trail_cmd.add_argument('--code',type=int,required=True)
    trail_cmd.add_argument('--group-id',required=True)
    trail_cmd.add_argument('--limit',type=int,default=40)
    trail_cmd.set_defaults(fn=trail)
    args=parser.parse_args()
    if args.command=='watch':
        if not 3<=args.segment_seconds<=120 or args.print_limit<0:
            parser.error('--segment-seconds 3..120 and --print-limit >=0 required')
        args.labels=load_labels(args.labels)
    if args.command in ('near','match'):
        if args.radius<0 or args.limit<1 or (args.within_minutes is not None
                                              and args.within_minutes<0):
            parser.error('radius >=0, limit >=1, within-minutes >=0 required')
    args.fn(args)


if __name__=='__main__':
    main()
