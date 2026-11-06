#!/usr/bin/env python3
"""Time-correlate manually observed game events with passive map sightings.

Does not infer a confirmed despawn from missing network records.
Does not send game requests or control BlueStacks.

  python network_scan/entity_event_audit.py mark --session network_scans/entity_live/SESSION --label visible --x 160 --y 687
  python network_scan/entity_event_audit.py mark --session network_scans/entity_live/SESSION --label defeated --x 160 --y 687
  python network_scan/entity_event_audit.py report --session network_scans/entity_live/SESSION --x 160 --y 687 --radius 15

Evidence timestamps are capture FILE closure times (approximate); event
markers are when the user runs the command on the host clock. A five-second
window can mix messages from before and after the marked event.
"""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from live_entity_watch import ROOT, append_csv, latest_session, read_csv
from scan import save_csv

MARK_FIELDS = ('marked_at_utc','label','server','x','y','visible_level','note')
REPORT_FIELDS = ('server','entity_key','x','y','type_code','subtype','candidate_group_id',
                 'shared_id_observed','distance','before_sightings','after_sightings',
                 'first_seen','last_seen','assessment')


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def parse_time(value):
    if not value:return None
    try:
        result=datetime.fromisoformat(str(value).replace('Z','+00:00'))
    except ValueError as exc:
        raise ValueError('Invalid ISO timestamp: '+str(value)) from exc
    if result.tzinfo is None:
        raise ValueError('Timestamp must include timezone offset')
    return result.astimezone(timezone.utc)


def mark(args):
    folder=args.session or latest_session(ROOT)
    folder.mkdir(parents=True,exist_ok=True)
    when=utc_now()
    row=dict(marked_at_utc=when,label=args.label,server=args.server,
             x=args.x,y=args.y,visible_level=args.visible_level or '',
             note=args.note or '')
    append_csv(folder/'event_marks.csv',MARK_FIELDS,[row])
    print('Event marked:',args.label,'S'+str(args.server),
          'X:'+str(args.x),'Y:'+str(args.y),when)
    if args.visible_level and args.visible_level>=100:
        print('Game rule: a confirmed creature level >=100 is a Watcher.')
    print('This mark reflects your visual observation, not a decoded death event.')
    print('Saved:',folder/'event_marks.csv')


def cutoff_from_marks(folder,args):
    if args.cutoff:
        return parse_time(args.cutoff)
    candidates=[r for r in read_csv(folder/'event_marks.csv')
                if str(r.get('label'))=='defeated'
                and str(r.get('server'))==str(args.server)
                and str(r.get('x'))==str(args.x)
                and str(r.get('y'))==str(args.y)]
    if not candidates:
        raise ValueError('No matching defeated marker. Record one with mark --label '
                         'defeated, or supply --cutoff ISO-8601 timestamp.')
    return parse_time(candidates[-1]['marked_at_utc'])


def compare_sightings(folder,args,cutoff):
    start=cutoff-timedelta(minutes=args.minutes)
    end=cutoff+timedelta(minutes=args.minutes)
    groups=defaultdict(list)
    for r in read_csv(folder/'entity_sightings.csv'):
        if str(r.get('server'))!=str(args.server):continue
        try:
            dx=int(r['x'])-args.x;dy=int(r['y'])-args.y
            distance=(dx*dx+dy*dy)**.5
            seen=parse_time(r.get('seen_at_utc'))
        except (TypeError,ValueError,KeyError):
            continue
        if seen is None or distance>args.radius or not start<=seen<=end:
            continue
        key=r.get('entity_key') or (
            f"{r.get('type_code')}:{r.get('subtype')}:{r.get('x')}:{r.get('y')}")
        groups[key].append((seen,distance,r))
    output=[]
    for key,items in groups.items():
        items.sort(key=lambda v:v[0])
        before=sum(when<cutoff for when,_,_ in items)
        after=len(items)-before
        first,last=items[0],items[-1]
        r=last[2]
        interpretation=('seen_on_both_sides' if before and after else
                        'not_seen_after_mark_NOT_proof_of_despawn' if before else
                        'first_seen_after_mark')
        output.append(dict(server=args.server,entity_key=key,
            x=r['x'],y=r['y'],type_code=r['type_code'],
            subtype=r.get('subtype') or '',
            candidate_group_id=r.get('candidate_group_id') or '',
            shared_id_observed=r.get('candidate_group_ambiguous') or '',
            distance=round(last[1],2),
            before_sightings=before,after_sightings=after,
            first_seen=first[0].isoformat(),last_seen=last[0].isoformat(),
            assessment=interpretation))
    output.sort(key=lambda r:(r['distance'],-r['before_sightings'],int(r['type_code'])))
    return output


def message_stats(folder,cutoff,minutes):
    before=dict(windows=0,views=0,updates=0,incoming_packets=0)
    after=before.copy()
    start=cutoff-timedelta(minutes=minutes)
    end=cutoff+timedelta(minutes=minutes)
    for r in read_csv(folder/'segments.csv'):
        try:seen=parse_time(r.get('observed_at_utc'))
        except ValueError:continue
        if seen is None or not start<=seen<=end:continue
        dest=before if seen<cutoff else after
        dest['windows']+=1
        for field,name in [('decoded_views','views'),('decoded_updates','updates'),
                           ('incoming_packets','incoming_packets')]:
            dest[name]+=int(r.get(field) or 0)
    return before,after


def report(args):
    folder=args.session or latest_session(ROOT)
    cutoff=cutoff_from_marks(folder,args)
    rows=compare_sightings(folder,args,cutoff)
    before,after=message_stats(folder,cutoff,args.minutes)
    print(f'Event audit: S{args.server} X:{args.x} Y:{args.y}, '
          f'radius {args.radius}, +/-{args.minutes} minutes.')
    print('Defeated marker (host UTC):',cutoff.isoformat())
    print('BEFORE: {windows} windows, {views} views, {updates} updates, '
          '{incoming_packets} incoming packets'.format(**before))
    print('AFTER : {windows} windows, {views} views, {updates} updates, '
          '{incoming_packets} incoming packets'.format(**after))
    print('Candidate entity positions within radius:',len(rows))
    for r in rows[:args.limit]:
        print('  X:{x} Y:{y} type:{type_code} subtype:{subtype} '
              'd:{distance:.1f} before:{before_sightings} after:{after_sightings} '
              '{assessment}'.format(**r))
    if not rows:
        print('No qualifying entity sightings. This cannot establish what object died.')
    if after['views']+after['updates']==0:
        print('CRITICAL: no decoded map messages after kill mark. '
              'Cannot evaluate whether this object persisted.')
    else:
        print('Map responses followed the kill marker, but missing a candidate '
              'still does not establish a despawn: viewport coverage and '
              'update-delete fields remain unverified.')
    print('Capture timestamps may straddle the manual kill marker by several seconds.')
    out=args.out or folder/'event_audit.csv'
    save_csv(out,REPORT_FIELDS,rows)
    print('Saved:',out)


def main():
    parser=argparse.ArgumentParser(description=__doc__,
       formatter_class=argparse.RawDescriptionHelpFormatter)
    commands=parser.add_subparsers(dest='cmd',required=True)
    m=commands.add_parser('mark',help='Record visible/defeated state while live watcher is running')
    m.add_argument('--session',type=Path)
    m.add_argument('--label',choices=['visible','defeated'],required=True)
    m.add_argument('--server',type=int,default=125)
    m.add_argument('--x',type=int,required=True)
    m.add_argument('--y',type=int,required=True)
    m.add_argument('--visible-level',type=int)
    m.add_argument('--note',default='')
    m.set_defaults(fn=mark)
    r=commands.add_parser('report',help='Audit before/after positive sightings')
    r.add_argument('--session',type=Path)
    r.add_argument('--server',type=int,default=125)
    r.add_argument('--x',type=int,required=True)
    r.add_argument('--y',type=int,required=True)
    r.add_argument('--radius',type=float,default=15)
    r.add_argument('--minutes',type=float,default=5)
    r.add_argument('--cutoff',help='UTC ISO timestamp override')
    r.add_argument('--out',type=Path)
    r.add_argument('--limit',type=int,default=30)
    r.set_defaults(fn=report)
    args=parser.parse_args()
    if args.cmd=='mark' and args.visible_level is not None and args.visible_level<1:
        parser.error('--visible-level must be positive')
    if args.cmd=='report' and (args.radius<0 or args.minutes<=0 or args.limit<1):
        parser.error('radius>=0, minutes>0, limit>=1 required')
    try:args.fn(args)
    except (ValueError,OSError,csv.Error) as exc:parser.error(str(exc))


if __name__=='__main__':
    main()
