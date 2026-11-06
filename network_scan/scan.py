#!/usr/bin/env python3
"""Z-Route network map coverage planner and passive capture runner.

Reads only network traffic observed while the real game client navigates.
Does not send, forge or replay game-server requests. Python 3.10+.

    python network_scan/scan.py analyze capture1.pcapng capture2.pcapng
    python network_scan/scan.py plan --pilot 522 415
    python network_scan/scan.py plan --out network_scans/full.csv
    python network_scan/scan.py run --plan network_scans/pilot.csv --interface 1
"""
import argparse
import csv
import json
import subprocess
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from zroute_map_decoder import (
    application_messages, decode_payload, extract_players, map_root,
    protobuf_fields, value
)

BASE_FIELDS = ('server','x','y','username','alliance_tag','alliance_name',
               'base_level','player_id','capture','time_s')
VIEW_FIELDS = ('capture','time_s','center_x','center_y','bases',
               'x_min','x_max','y_min','y_max','payload_bytes','format')
PLAN_FIELDS = ('id','x','y','status','attempts','bases','capture','updated_at')

def save_csv(path, fields, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    with temp.open('w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
    temp.replace(path)

def load_csv(path):
    with Path(path).open(newline='',encoding='utf-8-sig') as handle:
        return list(csv.DictReader(handle))

def inspect(path):
    """View extents are OBSERVED BASE locations, not proven viewport coverage."""
    views, failures = [], 0
    for name, when, payload in application_messages(Path(path)):
        if name != 'WorldMapViewS2C':
            continue
        try:
            decoded, fmt = decode_payload(payload)
            root = map_root(decoded)
            loc = protobuf_fields(value(root,4,2))
            center_x, center_y = value(loc,2,0), value(loc,3,0)
            bases = list(extract_players(root, Path(path).name, when))
        except (ValueError,TypeError,OSError,EOFError):
            failures += 1
            continue
        xs = [p['x'] for p in bases]
        ys = [p['y'] for p in bases]
        views.append((dict(capture=Path(path).name, time_s=round(when or 0,3),
                           center_x=center_x,center_y=center_y,bases=len(bases),
                           x_min=min(xs) if xs else '',x_max=max(xs) if xs else '',
                           y_min=min(ys) if ys else '',y_max=max(ys) if ys else '',
                           payload_bytes=len(payload),format=fmt),bases))
    return views, failures

def analyze(args):
    rows, latest, errors = [], {}, 0
    for file in args.captures:
        path=Path(file)
        if not path.is_file():
            raise SystemExit('Missing capture: '+str(path))
        views, failed = inspect(path)
        errors += failed
        for view, bases in views:
            rows.append(view)
            for player in bases:
                latest[(player['server'],player['player_id'])] = player
        print(f'{path.name}: {len(views)} views; {sum(len(b) for _,b in views)} observations; {failed} undecoded')
    save_csv(args.out/'views.csv',VIEW_FIELDS,rows)
    save_csv(args.out/'players.csv',BASE_FIELDS,sorted(latest.values(),key=lambda r:(r['server'],r['player_id'])))
    print(f'{len(latest)} unique bases, {len(set((r["center_x"],r["center_y"]) for r in rows))} distinct centers.')
    if rows:
        biggest=max(rows,key=lambda r:r['bases'])
        print('Biggest response:',biggest['bases'],'bases at',(biggest['center_x'],biggest['center_y']),
              'observed X',biggest['x_min'],'to',biggest['x_max'],
              'Y',biggest['y_min'],'to',biggest['y_max'])
    print('Saved:',args.out/'players.csv','and',args.out/'views.csv')
    if errors: print('WARNING:',errors,'undecoded responses; do not claim exhaustive coverage.')

def axis(low,high,step):
    if high<low or step<1: raise ValueError('Bad bounds or step')
    if high-low<step: return [(low+high)//2]
    result=[low+step//2]
    while result[-1]+step <= high-step//2:
        result.append(result[-1]+step)
    tail=high-step//2
    if tail-result[-1]>step//2:result.append(tail)
    return sorted(set(result))

def plan(args):
    if args.pilot:
        cx,cy=args.pilot
        xs=[cx-args.step_x,cx,cx+args.step_x]
        ys=[cy-args.step_y,cy,cy+args.step_y]
        xs=[v for v in xs if args.x_min<=v<=args.x_max]
        ys=[v for v in ys if args.y_min<=v<=args.y_max]
    else:
        xs=axis(args.x_min,args.x_max,args.step_x)
        ys=axis(args.y_min,args.y_max,args.step_y)
    if args.out.exists() and not args.force:
        raise SystemExit('Existing plan; choose a new --out or use --force')
    rows=[]
    for index,y in enumerate(ys):
        for x in (xs if index%2==0 else list(reversed(xs))):
            rows.append(dict(id=len(rows)+1,x=x,y=y,status='pending',
                             attempts=0,bases='',capture='',updated_at=''))
    save_csv(args.out,PLAN_FIELDS,rows)
    print(f'Created {len(rows)} targets: {args.out}')
    print('Experimental spacing only; test the pilot at a fixed zoom before a full run.')

def adb_call(adb,serial,*args):
    try:
        completed=subprocess.run([adb,'-s',serial,*args],capture_output=True,
                                 text=True,timeout=15)
    except (OSError,subprocess.TimeoutExpired) as exc:
        raise RuntimeError('ADB timed out. UI position is unverified; stopping.') from exc
    if completed.returncode:
        raise RuntimeError('ADB error: '+completed.stderr.strip())

def jump(target,ui,adb,serial):
    """Use only user-supplied and visually calibrated screen coordinates."""
    for action in ui['actions']:
        op=action['op']
        if op=='tap':
            adb_call(adb,serial,'shell','input','tap',str(int(action['x'])),str(int(action['y'])))
        elif op=='field':
            adb_call(adb,serial,'shell','input','tap',str(int(action['x'])),str(int(action['y'])))
            adb_call(adb,serial,'shell','input','keyevent','123')  # move to end
            for _ in range(5): adb_call(adb,serial,'shell','input','keyevent','67') # delete
            if action['value'] not in ('x','y'):
                raise ValueError('Field value must be x or y')
            adb_call(adb,serial,'shell','input','text',str(target[action['value']]))
        elif op=='sleep':
            time.sleep(max(0,min(5,float(action['seconds']))))
        else:
            raise ValueError('Unknown jump-ui action: '+str(op))

def run(args):
    rows=load_csv(args.plan)
    if not rows: raise SystemExit('Empty plan')
    ui=cfg=None
    if args.mode=='adb':
        if not args.jump_ui:
            raise SystemExit('ADB mode requires your calibrated --jump-ui JSON')
        ui=json.loads(args.jump_ui.read_text(encoding='utf-8'))
        if not ui.get('actions'):
            raise SystemExit('jump-ui must contain an actions array')
        cfg=json.loads(args.adb_config.read_text(encoding='utf-8'))
    folder=args.plan.parent/(args.plan.stem+'_captures')
    folder.mkdir(parents=True,exist_ok=True)
    for row in rows:
        if row['status']=='complete': continue
        x,y=int(row['x']),int(row['y'])
        for attempt in range(args.retries):
            row['attempts']=str(int(row.get('attempts') or 0)+1)
            name=f'target_{int(row["id"]):03d}_{x}_{y}_try{row["attempts"]}.pcapng'
            capture=folder/name
            print(f'\nTarget {row["id"]}/{len(rows)} — S:125 X:{x} Y:{y}')
            try:
                proc=subprocess.Popen([args.dumpcap,'-i',args.interface,
                     '-f','tcp port 9929','-a',f'duration:{args.seconds}',
                     '-w',str(capture)],stdout=subprocess.DEVNULL,
                     stderr=subprocess.PIPE,text=True)
            except OSError as exc:
                raise SystemExit('Cannot start dumpcap. Try --dumpcap full-path. '+str(exc))
            try:
                time.sleep(.5)
                if proc.poll() is not None:
                    raise RuntimeError('dumpcap could not capture: '+proc.communicate()[1])
                if args.mode=='manual':
                    print('Capture running. NOW jump to the target using the game UI.')
                    input('Press Enter after the map loads (Ctrl+C checkpoints): ')
                else:
                    jump(dict(x=x,y=y),ui,cfg.get('adb_path','adb'),
                         cfg.get('adb_serial','127.0.0.1:5555'))
                proc.wait(timeout=args.seconds+15)
            except KeyboardInterrupt:
                proc.terminate();proc.wait(timeout=5)
                save_csv(args.plan,PLAN_FIELDS,rows)
                raise SystemExit('Stopped; checkpoint saved.')
            except Exception as exc:
                print('Capture/navigation failed:',exc)
                if proc.poll() is None:
                    proc.terminate();proc.wait(timeout=5)
                row['status']='review'
                row['updated_at']=datetime.now(timezone.utc).isoformat()
                save_csv(args.plan,PLAN_FIELDS,rows)
                if args.mode=='adb':
                    print('Stopping unattended navigation; UI state is unknown.')
                    return
                continue
            views,failures=inspect(capture)
            nearby=[(view,bases) for view,bases in views
                    if abs(view['center_x']-x)<=args.tolerance
                    and abs(view['center_y']-y)<=args.tolerance]
            row['capture']=str(capture)
            row['updated_at']=datetime.now(timezone.utc).isoformat()
            row['bases']=str(len({p['player_id'] for _,bs in nearby for p in bs}))
            row['status']='complete' if nearby else 'review'
            print(f'{len(nearby)} responses near intended center; {row["bases"]} bases;',
                  f'uncoded messages: {failures}; status: {row["status"]}')
            if nearby: break
            if args.mode=='adb':
                print('No verified map response; check UI calibration before retry.')
                break
        save_csv(args.plan,PLAN_FIELDS,rows)
    print('Complete:',sum(r['status']=='complete' for r in rows),
          'of',len(rows),'targets. Checkpoint:',args.plan)
    print('Analyze saved PCAPNG files in:',folder)

def main():
    p=argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    subs=p.add_subparsers(dest='command',required=True)
    a=subs.add_parser('analyze')
    a.add_argument('captures',nargs='+')
    a.add_argument('--out',type=Path,default=Path('network_scans/analysis'))
    a.set_defaults(fn=analyze)
    a=subs.add_parser('plan')
    a.add_argument('--out',type=Path,default=Path('network_scans/plan.csv'))
    for axisname in ('x','y'):
        a.add_argument('--'+axisname+'-min',type=int,default=0)
        a.add_argument('--'+axisname+'-max',type=int,default=999)
        a.add_argument('--step-'+axisname,type=int,default=110 if axisname=='x' else 140)
    a.add_argument('--pilot',nargs=2,type=int,metavar=('X','Y'))
    a.add_argument('--force',action='store_true')
    a.set_defaults(fn=plan)
    a=subs.add_parser('run')
    a.add_argument('--plan',type=Path,required=True)
    a.add_argument('--interface',required=True,help='From dumpcap -D')
    a.add_argument('--dumpcap',default='dumpcap')
    a.add_argument('--seconds',type=int,default=18)
    a.add_argument('--retries',type=int,default=2)
    a.add_argument('--tolerance',type=int,default=8)
    a.add_argument('--mode',choices=['manual','adb'],default='manual')
    a.add_argument('--jump-ui',type=Path)
    a.add_argument('--adb-config',type=Path,default=Path('config.json'))
    a.set_defaults(fn=run)
    args=p.parse_args()
    if args.command=='run' and (args.seconds<5 or args.retries<1 or args.retries>5):
        p.error('--seconds must be >=5 and retries between 1 and 5')
    args.fn(args)
if __name__=='__main__':
    main()
