#!/usr/bin/env python3
"""Explore Z-Route map objects and unknown player status fields from saved PCAPNG.

No live capture, ADB clicks, or game-server requests. The schema is
reverse-engineered from WorldMapViewS2C and is NOT an official API.

Example (from repository root, PowerShell):
  python network_scan/map_entity_probe.py
  python network_scan/map_entity_probe.py --max-files 12
  python network_scan/map_entity_probe.py --captures my_capture.pcapng

Outputs under network_scans/map_entities:
  type_inventory.csv, world_objects.csv, player_status.csv,
  type_samples.json, entity_summary.json, object_observations.csv

Player-base field 9 is the accepted shield flag: 1=shielded, absent=unshielded
in a decoded player record. Other values are unknown. Original raw status bits
and approximate network-observation timestamps are retained.
Non-player type identities remain unknown until visually validated.
Captures and outputs may contain private game data; never publish by default.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from scan import save_csv
from shield_state import decode_shield_status
from zroute_map_decoder import (application_messages, decode_payload, map_root,
                                protobuf_fields, value)

WORLD_FIELDS = ('server','x','y','type_code','type_label','classification',
                'subtype','detail_field','raw_object_field1','raw_location_field4',
                'detail_scalar_json','detail_text_json','first_capture','last_capture',
                'first_seen_utc','last_seen_utc','observations','world_key')
STATUS_FIELDS = ('server','player_id','username','x','y','base_level',
                 'alliance_tag','status_9','status_13','status_15',
                 'status_18','status_18_utc','status_23',
                 'raw_extra_scalars_json','shield_status','capture','observed_at_utc')
TYPE_FIELDS = ('type_code','type_label','classification','observations',
               'unique_positions','unique_world_keys','detail_field',
               'subtype_examples','sample_coordinate','field_patterns')
OBS_FIELDS = ('capture','time_s','server','x','y','type_code','type_label',
              'subtype','raw_object_field1','world_key')
FIELD_NAMES = {1:'player_base'}  # All other code names need visual verification.
DETAIL_FIELD = {1:4,3:5,5:6,6:7,9:9,10:8,1001:18,2001:25,
                9899:28,9900:26,9916:19,9917:19}


def signed64(v):
    if v is None:
        return None
    return v - (1 << 64) if v >= 1 << 63 else v


def timestamp_utc(value):
    """Display a timestamp-looking integer, without asserting its meaning."""
    if value is None or not 978307200000 <= value <= 4102444800000:
        return ''
    try:
        return datetime.fromtimestamp(value/1000,timezone.utc).isoformat()
    except (OverflowError, ValueError, OSError):
        return ''


def decode_text(value_bytes):
    try:
        text = value_bytes.decode('utf-8')
    except UnicodeDecodeError:
        return None
    return text if text.isprintable() and len(text)<=96 else None


def detail_values(fields):
    """Summarize direct scalar fields; don't invent names for protobuf tags."""
    scalars, strings = {}, {}
    for n,w,v in fields:
        if w in (0,1,5):
            scalars.setdefault(str(n), []).append(signed64(v) if w==0 else v)
        elif w==2:
            t=decode_text(v)
            if t is not None:
                strings.setdefault(str(n), []).append(t)
    return scalars,strings


def parse_object(blob):
    obj = protobuf_fields(blob)
    code = signed64(value(obj, 3, 0))
    if code is None:
        return None
    loc_blob=value(obj,2,2)
    if loc_blob is None:
        return None
    loc=protobuf_fields(loc_blob)
    server,x,y=(value(loc,i,0) for i in (1,2,3))
    if (None in (server,x,y) or not(1<=server<=10000) or
        not(0<=x<=5000) or not(0<=y<=5000)):
        return None
    direct = [(n,w,v) for n,w,v in obj if w==2 and n!=2]
    detail_field=DETAIL_FIELD.get(code, direct[0][0] if direct else None)
    raw_detail=value(obj,detail_field,2) if detail_field else None
    detail=protobuf_fields(raw_detail) if raw_detail is not None else []
    scalars,strings=detail_values(detail)
    subtype=signed64(value(detail,1,0))
    if code==1:
        username=value(detail,4,2)
        pid=value(detail,1,0)
        if username is None or pid is None:
            return None
        decoded=decode_text(username)
        if not decoded:
            return None
    else:
        pid=None
    return dict(server=server,x=x,y=y,type_code=code,
                raw_object_field1=value(obj,1,0),
                raw_location_field4=value(loc,4,0),
                detail_field=detail_field,
                detail_scalars=scalars,detail_text=strings,
                subtype=subtype,detail=detail,
                player_id=pid,
                type_field_signature=','.join(f'{n}:{w}' for n,w,_ in obj))


def world_key(p):
    """Position + type + subtype dedup; not guaranteed stable object identity."""
    token=f"{p['server']}:{p['type_code']}:{p['x']}:{p['y']}:{p['subtype']}"
    return hashlib.sha256(token.encode('utf-8')).hexdigest()[:20]


def status_record(p, capture, observed_at):
    detail=p['detail']
    raw_flags={str(n): signed64(v) for n,w,v in detail if w==0 and n not in
               (1,2,5,11,12,14,19,20,31)}
    extra=lambda n:value(detail,n,0)
    tag=decode_text(value(detail,6,2,b'')) or ''
    return dict(server=p['server'],player_id=p['player_id'],
                username=decode_text(value(detail,4,2,b'')) or '',
                x=p['x'],y=p['y'],base_level=extra(2),alliance_tag=tag,
                status_9=extra(9),status_13=extra(13),status_15=extra(15),
                status_18=extra(18),status_18_utc=timestamp_utc(extra(18)),
                status_23=extra(23),
                raw_extra_scalars_json=json.dumps(raw_flags,separators=(',',':')),
                shield_status=decode_shield_status(extra(9)),capture=capture,
                observed_at_utc=observed_at)


def discover(root):
    paths = sorted((root/'live').glob('*/captures/*.pcapng'))
    paths += sorted((root/'full_map'/'captures').glob('*.pcapng'))
    return sorted(set(paths))


def load_labels(file):
    if file is None:
        return {}
    data=json.loads(file.read_text(encoding='utf-8'))
    if not isinstance(data,dict):
        raise ValueError('Labels JSON must be an object mapping type codes to descriptions')
    labels={}
    for code,info in data.items():
        int(code)
        if not isinstance(info,dict):
            raise ValueError('Each type label must include name and verified boolean')
        name=str(info.get('name','')).strip()
        if not name or len(name)>64:
            raise ValueError('Invalid type name')
        labels[int(code)]=(name,bool(info.get('verified',False)))
    return labels


def observed_at(path, relative_time):
    # Actual packet timestamp is not absolute in this lightweight decoder.
    # Capture file mtime is only a proxy; do NOT claim exact object spawn time.
    return datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat()


def classify(code,labels):
    if code==1:return 'Player base','verified_decoder'
    item=labels.get(code)
    if item:
        return item[0],('visually_verified' if item[1] else 'unverified_manual_label')
    return f'Unclassified type {code}','unknown'


def run(args):
    files=list(args.captures or discover(args.network_root))
    if not files:
        raise SystemExit('No PCAPNG captures found. Point --captures to saved capture files, '
                         'or retain PCAPNGs under network_scans/live/.../captures/.')
    if args.max_files:
        files=files[:args.max_files]
    labels=load_labels(args.labels)
    args.out.mkdir(parents=True,exist_ok=True)
    type_count=Counter()
    type_positions=defaultdict(set)
    type_subtypes=defaultdict(Counter)
    type_signatures=defaultdict(Counter)
    samples={}
    latest_objects={}
    latest_status={}
    parse_errors=Counter()
    decoded_views=0
    rows=0
    out_observations=args.out/'object_observations.csv'
    # Streaming CSV of all observed objects. Large overnight captures can
    # contain hundreds of thousands of records; do not retain all in RAM.
    with out_observations.open('w',encoding='utf-8-sig',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=OBS_FIELDS)
        writer.writeheader()
        for index,path in enumerate(files,1):
            captures=0
            for name,relative_time,raw in application_messages(path):
                if name!='WorldMapViewS2C':
                    parse_errors['update_messages_skipped']+=1
                    continue
                try:
                    decoded,_=decode_payload(raw)
                    root=map_root(decoded)
                except (ValueError,TypeError,OSError,EOFError):
                    parse_errors['undecoded_view']+=1
                    continue
                decoded_views+=1
                for fn,w,blob in root:
                    if fn!=5 or w!=2:
                        continue
                    try:
                        entity=parse_object(blob)
                    except (ValueError,TypeError,UnicodeDecodeError):
                        parse_errors['invalid_object']+=1
                        continue
                    if entity is None:
                        parse_errors['skipped_object']+=1
                        continue
                    code=entity['type_code']
                    key=world_key(entity)
                    label,classification=classify(code,labels)
                    type_count[code]+=1
                    type_positions[code].add((entity['server'],entity['x'],entity['y']))
                    type_subtypes[code][str(entity['subtype'])]+=1
                    type_signatures[code][entity['type_field_signature']]+=1
                    sample=samples.setdefault(code,dict(server=entity['server'],
                        x=entity['x'],y=entity['y'],subtype=entity['subtype'],
                        detail_field=entity['detail_field'],
                        detail_scalars=entity['detail_scalars'],
                        detail_text=entity['detail_text'],
                        type_field_signature=entity['type_field_signature']))
                    when=observed_at(path,relative_time)
                    writer.writerow(dict(capture=path.name,time_s=relative_time,
                        server=entity['server'],x=entity['x'],y=entity['y'],
                        type_code=code,type_label=label,subtype=entity['subtype'],
                        raw_object_field1=entity['raw_object_field1'],world_key=key))
                    rows+=1
                    if code==1:
                        status=status_record(entity,path.name,when)
                        stable=(str(entity['server']),str(entity['player_id']))
                        latest_status[stable]=status
                    else:
                        previous=latest_objects.get(key)
                        latest_objects[key]=dict(server=entity['server'],x=entity['x'],
                            y=entity['y'],type_code=code,type_label=label,
                            classification=classification,subtype=entity['subtype'],
                            detail_field=entity['detail_field'],
                            raw_object_field1=entity['raw_object_field1'],
                            raw_location_field4=entity['raw_location_field4'],
                            detail_scalar_json=json.dumps(entity['detail_scalars'],
                                ensure_ascii=False,separators=(',',':')),
                            detail_text_json=json.dumps(entity['detail_text'],
                                ensure_ascii=False,separators=(',',':')),
                            first_capture=previous['first_capture'] if previous else path.name,
                            last_capture=path.name,
                            first_seen_utc=previous['first_seen_utc'] if previous else when,
                            last_seen_utc=when,
                            observations=previous['observations']+1 if previous else 1,
                            world_key=key)
            print(f'[{index}/{len(files)}] {path.name}: '
                  f'{rows:,} cumulative world objects, '
                  f'{len(latest_objects):,} non-player positions')
    inventories=[]
    for code,count in type_count.most_common():
        label,classification=classify(code,labels)
        sample=samples[code]
        inventories.append(dict(type_code=code,type_label=label,
            classification=classification,observations=count,
            unique_positions=len(type_positions[code]),
            unique_world_keys=sum(1 for p in latest_objects.values()
                                  if p['type_code']==code),
            detail_field=sample['detail_field'],
            subtype_examples=';'.join(f'{key}:{n}' for key,n in
                                      type_subtypes[code].most_common(8)),
            sample_coordinate=f"S{sample['server']} X{sample['x']} Y{sample['y']}",
            field_patterns='; '.join(f'{k} ({n})' for k,n in
                                      type_signatures[code].most_common(3))))
    save_csv(args.out/'world_objects.csv',WORLD_FIELDS,list(latest_objects.values()))
    save_csv(args.out/'type_inventory.csv',TYPE_FIELDS,inventories)
    save_csv(args.out/'player_status.csv',STATUS_FIELDS,list(latest_status.values()))
    (args.out/'type_samples.json').write_text(json.dumps(samples,ensure_ascii=False,indent=2),
                                                 encoding='utf-8')
    summary=dict(files=len(files),decoded_views=decoded_views,
                 world_object_observations=rows,
                 unique_nonplayer_positions=len(latest_objects),
                 player_records_with_raw_status=len(latest_status),
                 type_counts={str(k):v for k,v in type_count.most_common()},
                 parse_errors=dict(parse_errors),
                 shield_status='unverified',
                 walker_type='unverified',
                 note='World object type codes are unverified except type 1 player bases. '
                      'Observed_at_utc uses capture file mtime as an approximate proxy; '
                      'not proof of exact shield, spawn or walker state.')
    (args.out/'entity_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(f'DONE: {rows:,} object observations; '
          f'{len(latest_objects):,} distinct non-player object keys; '
          f'{len(latest_status):,} player status records; {len(type_count)} object types.')
    print('Saved',args.out.resolve())
    print('Shield state and walker classification are unverified: '
          'compare with screenshots at known world coordinates before labeling.')


def main():
    parser=argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--network-root',type=Path,default=Path('network_scans'))
    parser.add_argument('--out',type=Path,default=Path('network_scans/map_entities'))
    parser.add_argument('--captures',type=Path,nargs='+',
                        help='Explicit capture files. Default: saved live & full_map captures')
    parser.add_argument('--max-files',type=int,default=0,
                        help='Limit to first N captures for a quick pilot')
    parser.add_argument('--labels',type=Path,
                        help='Optional local type labels JSON; use verified=true only after UI check')
    args=parser.parse_args()
    if args.max_files<0:
        parser.error('--max-files must not be negative')
    try:
        run(args)
    except (ValueError,OSError,csv.Error,json.JSONDecodeError) as exc:
        parser.error(str(exc))


if __name__=='__main__':
    main()
