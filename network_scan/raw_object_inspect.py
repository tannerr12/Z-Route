#!/usr/bin/env python3
"""Offline raw protobuf inspection for world objects near a visible creature.

Unlike level-probe's selected detail scalars, this tool prints EVERY object
field and recursively inspects parseable length-delimited submessages.
Packed/opaque bytes are described in hex; they are not guessed as levels.

From the repository root:
  python network_scan/raw_object_inspect.py --session network_scans/entity_live/20261106_122600 --server 125 --x 160 --y 687 --radius 20 --visible-level 120

Only READS existing Wireshark PCAPNGs; it never connects to the game.
Output is private JSON under network_scans/. The capture file modification
time is not a guaranteed game event timestamp.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
from collections import Counter
from pathlib import Path

from live_entity_watch import decode_for_server
from map_entity_probe import parse_object, signed64
from zroute_map_decoder import application_messages, protobuf_fields


def parse_tree(data, max_depth=4, depth=0):
    """Return neutral raw protobuf field records, preserving unknown fields."""
    if depth > max_depth:
        return [{'truncated_depth': True}]
    fields=protobuf_fields(data)
    output=[]
    for number,wire,val in fields:
        rec={'field':number,'wire':wire}
        if wire==0:
            rec['unsigned']=int(val)
            rec['signed64']=signed64(val)
        elif wire in (1,5):
            rec['unsigned']=int(val)
            rec['encoding']='fixed64' if wire==1 else 'fixed32'
        elif wire==2:
            rec['bytes_length']=len(val)
            rec['hex_prefix']=val[:64].hex()
            # Only accept a textual interpretation if the whole string is
            # printable. A protobuf submessage may otherwise decode to gibberish.
            try:
                message=val.decode('utf-8')
                if message and len(message)<=120 and message.isprintable():
                    rec['printable_text']=message
            except UnicodeDecodeError:
                pass
            if depth < max_depth and val:
                try:
                    nested=protobuf_fields(val)
                    if nested:
                        rec['children']=parse_tree(val,max_depth,depth+1)
                except (ValueError,TypeError):
                    pass
        output.append(rec)
    return output


def numeric_matches(tree, target, path=''):
    """Find literal numeric matches at every parseable nested field path."""
    matches=[]
    for record in tree:
        if 'field' not in record:
            continue
        current=path+str(record['field'])
        if (record.get('unsigned')==target or record.get('signed64')==target):
            matches.append(current)
        if record.get('children'):
            matches.extend(numeric_matches(record['children'],target,current+'.'))
    return sorted(set(matches))


def read_objects(files, server, x, y, radius, max_per_object, max_depth):
    # One full application message may span two dumpcap rotation files.
    # Join consecutive capture sections in a temporary file, resynchronize
    # and deduplicate exact response bytes across overlapping reads.
    found={}
    summary=Counter()
    seen_messages=set()
    previous=None
    # A context-managed temporary directory avoids leaving readable joined
    # packet files or overwriting any user's capture.
    from tempfile import TemporaryDirectory
    with TemporaryDirectory(prefix='zroute_raw_probe_') as work:
        joined=Path(work)/'joined.pcapng'
        for i,file in enumerate(files,1):
            if previous is None:
                source=file
            else:
                with joined.open('wb') as target:
                    for part in (previous,file):
                        with part.open('rb') as stream:
                            shutil.copyfileobj(stream,target)
                source=joined
            try:
                messages=application_messages(source)
                for message_type,when,raw in messages:
                    fingerprint=hashlib.sha256(message_type.encode('ascii')+raw).hexdigest()
                    if fingerprint in seen_messages:
                        continue
                    seen_messages.add(fingerprint)
                    summary['seen_messages']+=1
                    try:
                        root=decode_for_server(raw,server)
                    except (ValueError,TypeError,EOFError,OSError):
                        summary['decode_failures']+=1
                        continue
                    summary['decoded_messages']+=1
                    for num,wire,blob in root:
                        if num!=5 or wire!=2:
                            continue
                        try:
                            entity=parse_object(blob)
                        except (ValueError,TypeError,UnicodeDecodeError):
                            continue
                        if entity is None or entity['server']!=server:
                            continue
                        distance=math.hypot(entity['x']-x,entity['y']-y)
                        if distance>radius:
                            continue
                        summary['nearby_object_observations']+=1
                        obj_key=(entity['server'],entity['type_code'],
                                 entity['x'],entity['y'],entity['raw_object_field1'])
                        data=found.setdefault(obj_key,{
                            'server':entity['server'],'type_code':entity['type_code'],
                            'x':entity['x'],'y':entity['y'],
                            'distance':round(distance,2),
                            'subtype':entity['subtype'],
                            'candidate_group_id':entity['raw_object_field1'],
                            'sightings':0,'capture_names':[],
                            'raw_samples':[],'seen_raw_sample_sha':set()})
                        data['sightings']+=1
                        if file.name not in data['capture_names']:
                            data['capture_names'].append(file.name)
                        blob_sha=hashlib.sha256(blob).hexdigest()
                        if (len(data['raw_samples'])<max_per_object
                                and blob_sha not in data['seen_raw_sample_sha']):
                            data['seen_raw_sample_sha'].add(blob_sha)
                            try:
                                tree=parse_tree(blob,max_depth)
                            except (ValueError,TypeError):
                                tree=[{'parse_error':'malformed object protobuf'}]
                            data['raw_samples'].append({
                                'capture':file.name,'map_message_type':message_type,
                                'blob_sha256':blob_sha,
                                'raw_fields':tree})
            except (ValueError,TypeError,OSError) as exc:
                summary['capture_errors']+=1
                print(f'WARNING: {file.name}: {exc}')
            previous=file
            if i%10==0 or i==len(files):
                print(f'Processed {i}/{len(files)} capture files; '
                      f'{len(found)} distinct nearby object anchors',flush=True)
    for row in found.values():
        del row['seen_raw_sample_sha']
    return sorted(found.values(),key=lambda p:(p['distance'],p['type_code'],
                                                 p['x'],p['y'])),dict(summary)


def run(args):
    if args.session is None and not args.captures:
        raise SystemExit('Specify --session or --captures')
    files=list(args.captures or sorted(
        (args.session/'captures').glob('*.pcapng'),
        key=lambda p:(p.stat().st_mtime_ns,p.name)))
    if not files:
        raise SystemExit('No saved PCAPNG capture files found.')
    if args.max_files:
        files=files[:args.max_files]
    for file in files:
        if not file.is_file():
            raise SystemExit(f'Capture file does not exist: {file}')
    found,stats=read_objects(files,args.server,args.x,args.y,args.radius,
                            args.samples_per_object,args.depth)
    for rec in found[:args.limit]:
        print(f'\n[{rec["distance"]:.1f} tiles] S{rec["server"]} '
              f'X:{rec["x"]} Y:{rec["y"]} type:{rec["type_code"]} '
              f'subtype:{rec["subtype"]} candidate ID:{rec["candidate_group_id"]}')
        print(f'  sightings:{rec["sightings"]}, '
              f'source files:{", ".join(rec["capture_names"][:4])}')
        for sample in rec['raw_samples']:
            matched=numeric_matches(sample['raw_fields'],args.visible_level)
            print(f'  {sample["map_message_type"]}: '
                  f'raw field paths equal to visible level {args.visible_level}: '
                  f'{", ".join(matched) if matched else "none"}')
            print('  All object fields: '+json.dumps(
                sample['raw_fields'],ensure_ascii=False,separators=(',',':')))
    if len(found)>args.limit:
        print(f'  ...{len(found)-args.limit} more anchors in JSON output.')
    out=args.out or ((args.session or Path('network_scans/map_entities'))/
                     'raw_object_probe.json')
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps({
        'query':dict(server=args.server,x=args.x,y=args.y,radius=args.radius,
                     visible_level=args.visible_level,
                     samples_per_object=args.samples_per_object,
                     recursive_depth=args.depth),
        'summary':stats,
        'warning':('Raw numeric matches do NOT confirm that a field is the '
                   'creature level, nor that the matched object is a Watcher.'),
        'objects':found},indent=2,ensure_ascii=False),encoding='utf-8')
    print('\nDistinct nearby object anchors:',len(found))
    print('Messages decoded:',stats.get('decoded_messages',0),
          '| failed:',stats.get('decode_failures',0))
    print('Saved private report:',out.resolve())


def main():
    p=argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--session',type=Path)
    p.add_argument('--captures',type=Path,nargs='+')
    p.add_argument('--server',type=int,default=125)
    p.add_argument('--x',type=int,required=True)
    p.add_argument('--y',type=int,required=True)
    p.add_argument('--radius',type=float,default=20)
    p.add_argument('--visible-level',type=int,required=True)
    p.add_argument('--samples-per-object',type=int,default=2)
    p.add_argument('--depth',type=int,default=4)
    p.add_argument('--max-files',type=int,default=0)
    p.add_argument('--limit',type=int,default=20)
    p.add_argument('--out',type=Path)
    a=p.parse_args()
    if (a.radius<0 or a.visible_level<=0 or a.samples_per_object<1
            or a.samples_per_object>5 or not 0<=a.depth<=6
            or a.limit<1 or a.max_files<0):
        p.error('invalid radius/visible-level/samples/depth/limit settings')
    run(a)


if __name__=='__main__':
    main()
