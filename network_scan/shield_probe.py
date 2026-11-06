#!/usr/bin/env python3
"""Passive Z-Route shield-state calibration from visually verified bases.

Never infers shield presence from unknown protobuf fields without controls.
Capture and raw data remain local under network_scans/.

Workflow, with network_scan/live_entity_watch.py watch in another terminal:
  python network_scan/shield_probe.py inspect --session network_scans/entity_live/SESSION --x 500 --y 450
  python network_scan/shield_probe.py mark --session network_scans/entity_live/SESSION --x 500 --y 450 --state shielded
  # Move map away/back to provoke fresh map response without changing shield
  # Change shield state on the SAME base, then mark and refresh again
  python network_scan/shield_probe.py mark --session network_scans/entity_live/SESSION --player-id 123 --state unshielded
  python network_scan/shield_probe.py compare --session network_scans/entity_live/SESSION --player-id 123

The session's capture-file modification times are only APPROXIMATE network
observation times. The marker is a user-declared visual observation. Absence
of a flag in an update is not proof of absence of a shield.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from collections import Counter,defaultdict
from datetime import datetime,timezone,timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from live_entity_watch import ROOT, append_csv, decode_for_server, latest_session, read_csv
from map_entity_probe import parse_object, signed64
from zroute_map_decoder import application_messages,protobuf_fields, value

MARK_FIELDS=('marked_at_utc','state','server','player_id','username',
             'x','y','evidence','note')
IDENTITY_FIELDS=('server','player_id','username','x','y','observed_at_utc')
DIFF_FIELDS=('field_path','shielded_values','unshielded_values','shielded_samples',
             'unshielded_samples','interpretation')
META_FIELDS=('observed_at_utc','capture','message_type','server','player_id',
             'username','x','y','state_marker','marker_at_utc','detail_sha')


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def read_time(value):
    when=datetime.fromisoformat(value.replace('Z','+00:00'))
    if when.tzinfo is None:raise ValueError('Expected offset-aware timestamp: '+value)
    return when.astimezone(timezone.utc)


def safe_text(raw):
    if isinstance(raw,bytes):
        try:
            text=raw.decode('utf-8')
            if text and len(text)<120 and text.isprintable():
                return text
        except UnicodeDecodeError:
            pass
        return '0x'+raw.hex()
    return str(raw)


def detail_map(detail):
    """Preserve ALL direct field values (including bytes), not a handpicked
    subset of unverified shield-related scalar tags."""
    result=defaultdict(list)
    for n,w,v in detail:
        if w==0:
            rendered=str(signed64(v))
        elif w in (1,5):
            rendered=str(v)
        else:
            rendered=safe_text(v)
        result[f'{n}:{w}'].append(rendered)
    return {k:tuple(sorted(values)) for k,values in result.items()}


def resolve_player(session,server,player_id=None,x=None,y=None):
    if player_id is not None:
        player_id=str(player_id)
    rows=read_csv(session/'player_status_sightings.csv')
    matches=[]
    for row in rows:
        if str(row.get('server'))!=str(server):continue
        if player_id is not None and str(row.get('player_id'))!=player_id:
            continue
        if x is not None and str(row.get('x'))!=str(x):continue
        if y is not None and str(row.get('y'))!=str(y):continue
        if row.get('player_id'):
            matches.append(row)
    if not matches:
        if player_id is not None:
            return dict(server=server,player_id=player_id,
                        username='',x=x or '',y=y or '')
        raise ValueError('No saved player-base observation at those coordinates. '
                         'Navigate to the base with live watch running, wait for '
                         'a decoded map response, or pass --player-id explicitly.')
    ids={str(row['player_id']) for row in matches}
    if len(ids)>1:
        raise ValueError('Multiple player IDs matched; pass --player-id explicitly. '
                         'Coordinates can be reused or a base can move: '+', '.join(sorted(ids)))
    row=matches[-1]
    return dict(server=row['server'],player_id=row['player_id'],
                username=row.get('username') or '',x=row.get('x') or '',
                y=row.get('y') or '')



def require_session(path):
    """Reject placeholder/missing session folders instead of saying no players."""
    if path is None:
        return latest_session(ROOT)
    path=Path(path)
    if not path.is_dir():
        known=sorted(
            (p for p in ROOT.glob('*') if p.is_dir() and
             (p/'segments.csv').is_file()),
            key=lambda p:p.stat().st_mtime,reverse=True)
        recent=', '.join(str(p) for p in known[:3]) or '(none yet)'
        raise ValueError('Capture session folder not found: '+str(path)+'. '
                         'SESSION is a placeholder, not a literal folder name. '
                         'Start live_entity_watch.py watch in another PowerShell '
                         'window and use the path printed after "Private session:". '
                         'Recent sessions: '+recent)
    return path



def inspect(args):
    session=require_session(args.session)
    rows=read_csv(session/'player_status_sightings.csv')
    if not rows:
        segments=read_csv(session/'segments.csv')
        views=sum(int(r.get('decoded_views') or 0) for r in segments)
        updates=sum(int(r.get('decoded_updates') or 0) for r in segments)
        print(f'No player-base observations saved in {session}. '
              f'Decoded so far: {views} full map views, {updates} map updates.')
        print('Keep live_entity_watch.py watch RUNNING in another PowerShell '
              'window. Navigate away from the target base and back, wait '
              'for a completed 5-second capture window, then retry.')
        print('Make sure --x and --y are the BASE coordinates rather '
              'than the camera center. A blue dome is visual shield evidence, '
              'not proof of a decoded shield field.')
        return
    candidates=[]
    for r in rows:
        if str(r.get('server'))!=str(args.server):continue
        if args.player_id is not None and str(r.get('player_id'))!=str(args.player_id):
            continue
        if args.x is not None and abs(int(r['x'])-args.x)>args.radius:continue
        if args.y is not None and abs(int(r['y'])-args.y)>args.radius:continue
        candidates.append(r)
    latest={}
    for row in candidates:
        key=row['player_id']
        if key not in latest or str(row.get('seen_at_utc'))>str(latest[key].get('seen_at_utc')):
            latest[key]=row
    print(f'Found {len(latest)} unique player IDs near target in {session}')
    for r in sorted(latest.values(),key=lambda x:str(x.get('username','')))[:args.limit]:
        print(f'  {r.get("username")} ID:{r["player_id"]} '
              f'S{r["server"]} X:{r["x"]} Y:{r["y"]} '
              f'last:{r.get("seen_at_utc")} '
              f'flags9/13/15/18/23: '
              f'{r.get("status_9")},{r.get("status_13")},'
              f'{r.get("status_15")},{r.get("status_18")},'
              f'{r.get("status_23")} [UNVERIFIED]')
    if not latest:print('No matching player bases. Try a larger radius, or a new map capture.')


def mark(args):
    session=require_session(args.session)
    if args.evidence and not args.evidence.is_file():
        raise ValueError('Screenshot evidence file not found: '+str(args.evidence))
    who=resolve_player(session,args.server,args.player_id,args.x,args.y)
    row=dict(marked_at_utc=utc_now(),state=args.state,
             **who,evidence=str(args.evidence or ''),note=args.note or '')
    append_csv(session/'shield_marks.csv',MARK_FIELDS,[row])
    print(f'MARKED {args.state.upper()} VISUALLY: S{args.server} '
          f'player ID {who["player_id"]} {who["username"]} '
          f'X:{who["x"]} Y:{who["y"]}, {row["marked_at_utc"]}')
    print('Now navigate away and back to provoke a fresh passive map response '
          'while the marked shield state remains unchanged.')
    print('The marker is a visual observation, NOT a decoded network state.')


def iter_player_observations(files,server,player_id):
    """Extract complete player detail fields from all known received map
    messages, joining adjacent PCAPNG rotation files to recover splits."""
    previous=None
    seen_hashes={}
    with TemporaryDirectory(prefix='zroute_shield_probe_') as tempdir:
        joined=Path(tempdir)/'joined.pcapng'
        for index,file in enumerate(files):
            if previous is None:
                source=file
            else:
                with joined.open('wb') as out:
                    for part in (previous,file):
                        with part.open('rb') as inp:
                            shutil.copyfileobj(inp,out)
                source=joined
            try:
                for name,relative,raw in application_messages(source):
                    key=hashlib.sha256(name.encode('ascii')+raw).digest()
                    previous_index=seen_hashes.get(key)
                    if previous_index is not None and index-previous_index<=1:
                        continue  # only duplicate overlapping adjacent PCAP windows
                    seen_hashes[key]=index
                    try:
                        root=decode_for_server(raw,server)
                    except (ValueError,TypeError,OSError,EOFError):
                        continue
                    for num,wire,blob in root:
                        if num!=5 or wire!=2:continue
                        try:
                            player=parse_object(blob)
                        except (TypeError,ValueError,UnicodeDecodeError):
                            continue
                        if (not player or player['type_code']!=1
                                or str(player['server'])!=str(server)
                                or str(player['player_id'])!=str(player_id)):
                            continue
                        detail=player['detail']
                        seen=datetime.fromtimestamp(file.stat().st_mtime,
                                tz=timezone.utc)
                        username=value(detail,4,2,b'')
                        yield dict(observed_at_utc=seen.isoformat(timespec='seconds'),
                            capture=file.name,message_type=name,server=server,
                            player_id=player_id,username=safe_text(username),
                            x=player['x'],y=player['y'],details=detail_map(detail),
                            detail_sha=hashlib.sha256(repr(detail).encode()).hexdigest()[:20])
            except (OSError,ValueError) as exc:
                print('WARNING decoding '+file.name+': '+str(exc))
            previous=file


def assign_marks(observations,marks,window):
    """Match only responses captured AFTER a manual visual marker (conservative).
    Exact network event times cannot be recovered from current file mtime."""
    sorted_marks=sorted(marks,key=lambda m:read_time(m['marked_at_utc']))
    output=[]
    for obs in observations:
        when=read_time(obs['observed_at_utc'])
        preceding=[m for m in sorted_marks if m['state'] in ('shielded','unshielded')
                   and read_time(m['marked_at_utc'])<=when
                   and (when-read_time(m['marked_at_utc'])).total_seconds()<=window]
        if not preceding:continue
        current=preceding[-1]
        item=dict(obs,state_marker=current['state'],
                  marker_at_utc=current['marked_at_utc'])
        output.append(item)
    return output


def compare_fields(samples):
    grouped=defaultdict(list)
    for row in samples:
        grouped[row['state_marker']].append(row)
    shielded=grouped['shielded']
    unshielded=grouped['unshielded']
    if not shielded or not unshielded:
        return [],len(shielded),len(unshielded)
    keys=set()
    for record in samples:
        keys.update(record['details'])
    out=[]
    for key in keys:
        values={}
        for state,records in (('shielded',shielded),('unshielded',unshielded)):
            observations=[]
            for rec in records:
                data=rec['details'].get(key,('<ABSENT>',))
                observations.append('|'.join(data))
            values[state]=Counter(observations)
        if set(values['shielded'])==set(values['unshielded']):
            continue  # frequency of identical map responses is not a shield field
        # Samples can repeat because identical views are sent repeatedly.
        # Field names like timestamp, base level, and username are not
        # assigned meanings or tagged as shields.
        distinct1=set(values['shielded'])
        distinct2=set(values['unshielded'])
        stable= len(distinct1)==1 and len(distinct2)==1 and distinct1!=distinct2
        out.append(dict(field_path=key,
            shielded_values=json.dumps(values['shielded'],ensure_ascii=False),
            unshielded_values=json.dumps(values['unshielded'],ensure_ascii=False),
            shielded_samples=len(shielded),unshielded_samples=len(unshielded),
            interpretation=('consistent_difference_UNVERIFIED' if stable else
                            'variable_difference_UNVERIFIED')))
    out.sort(key=lambda r:(r['interpretation']!='consistent_difference_UNVERIFIED',
                           tuple(int(v) for v in r['field_path'].split(':'))))
    return out,len(shielded),len(unshielded)


def compare(args):
    session=require_session(args.session)
    mark_rows=read_csv(session/'shield_marks.csv')
    if not mark_rows:
        raise ValueError('No visual marks; use mark first.')
    marks=[m for m in mark_rows if str(m.get('server'))==str(args.server)
           and (args.player_id is None or str(m.get('player_id'))==str(args.player_id))]
    ids={str(m['player_id']) for m in marks}
    if len(ids)!=1:
        raise ValueError('Must select ONE stable player ID having both shielded '
                         'and unshielded marks: '+', '.join(sorted(ids)))
    player_id=next(iter(ids))
    files=sorted((session/'captures').glob('*.pcapng'),
                 key=lambda p:(p.stat().st_mtime_ns,p.name))
    if not files:raise ValueError('No saved PCAPNG captures in '+str(session))
    all_obs=list(iter_player_observations(files,args.server,player_id))
    sampled=assign_marks(all_obs,marks,args.window_seconds)
    differences,count_on,count_off=compare_fields(sampled)
    print(f'Analyzed player {player_id} S{args.server} from {len(files)} capture files.')
    print(f'Map observations: {len(all_obs)}; aligned after visual marks: '
          f'{count_on} shielded / {count_off} unshielded.')
    if not count_on or not count_off:
        print('INSUFFICIENT COMPARISON: need at least one map observation of '
              'the SAME player after each separately marked visual state. '
              'Mark the state and navigate away/back while live capture runs.')
    else:
        if not differences:
            print('No differing DIRECT protobuf detail fields detected. '
                  'Shield state may be in map updates beyond these details, '
                  'a different message, or encoded in a rendering asset.')
        else:
            print('Direct protobuf fields differing between visual states:')
            for row in differences:
                print(f'  field {row["field_path"]}: '
                      f'shielded {row["shielded_values"]} '
                      f'unshielded {row["unshielded_values"]} '
                      f'[{row["interpretation"]}]')
            print('Differences are CORRELATIONS, not confirmed shield flags. '
                  'Verify on additional shield toggles and bases.')
    output=session/'shield_probe'
    output.mkdir(exist_ok=True)
    with (output/'sampled_observations.json').open('w',encoding='utf-8') as out:
        json.dump(sampled,out,indent=2,ensure_ascii=False)
    from scan import save_csv
    save_csv(output/'field_differences.csv',DIFF_FIELDS,differences)
    print('Saved:',output/'sampled_observations.json',output/'field_differences.csv')


def main():
    p=argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    cmds=p.add_subparsers(dest='command',required=True)
    inspect_p=cmds.add_parser('inspect',help='Find player IDs and unknown raw flags near a base')
    inspect_p.add_argument('--session',type=Path)
    inspect_p.add_argument('--server',type=int,default=125)
    inspect_p.add_argument('--player-id')
    inspect_p.add_argument('--x',type=int)
    inspect_p.add_argument('--y',type=int)
    inspect_p.add_argument('--radius',type=int,default=0)
    inspect_p.add_argument('--limit',type=int,default=30)
    inspect_p.set_defaults(fn=inspect)
    mark_p=cmds.add_parser('mark',help='Record visually confirmed shield state')
    mark_p.add_argument('--session',type=Path)
    mark_p.add_argument('--server',type=int,default=125)
    mark_p.add_argument('--player-id')
    mark_p.add_argument('--x',type=int)
    mark_p.add_argument('--y',type=int)
    mark_p.add_argument('--state',required=True,choices=['shielded','unshielded'])
    mark_p.add_argument('--evidence',type=Path)
    mark_p.add_argument('--note',default='')
    mark_p.set_defaults(fn=mark)
    compare_p=cmds.add_parser('compare',help='Compare visually verified shield states')
    compare_p.add_argument('--session',type=Path)
    compare_p.add_argument('--server',type=int,default=125)
    compare_p.add_argument('--player-id')
    compare_p.add_argument('--window-seconds',type=int,default=45,
        help='Accept captured map responses up to N seconds after each marker')
    compare_p.set_defaults(fn=compare)
    args=p.parse_args()
    if args.command=='inspect' and (args.radius<0 or args.limit<1):
        p.error('radius must be >=0 and limit >=1')
    if args.command=='compare' and not 5<=args.window_seconds<=180:
        p.error('window-seconds must be in 5..180')
    if args.command=='mark' and args.player_id is None and (args.x is None or args.y is None):
        p.error('mark requires --player-id or both --x and --y')
    try:args.fn(args)
    except (OSError,ValueError,csv.Error) as exc:p.error(str(exc))


if __name__=='__main__':
    main()
