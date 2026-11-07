#!/usr/bin/env python3
"""Continuous Wireshark capture + rapid, dense top-left serpentine radar taps.

All minimap taps are attempted without pause between groups. Capture runs in a
single dumpcap process, rotating PCAPNG segments for recoverable evidence.
A tap is NOT proof a new map view loaded. Saved checkpoints distinguish attempted
taps from confirmed decoded responses.
"""
from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from full_map_scan import load_players, player_key
from live_watch import decode_with_predecessor, resolve_interface, traffic_stats, view_signature
from pattern_benchmark import (adb_run, ensure_adb_device, load_adb_settings,
                               ordered, targets, verify_device)
from player_history import connection, ingest_records
from scan import BASE_FIELDS, save_csv


def save_json(path, obj):
    tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(obj,indent=2,ensure_ascii=False),encoding='utf-8')
    tmp.replace(path)


def fast_scan(args):
    """One 20x20 serpentine sweep; resume attempts with same output folder."""
    if args.pattern!='snake' or len(args.stages)!=1:
        raise ValueError('Fast sweep requires snake and a single grid size')
    if not .2<=args.fast_interval<1 or not 2<=args.fast_batch<=40:
        raise ValueError('Fast settings: interval 0.2..0.99s; checkpoint 2..40 taps')
    args.out.mkdir(parents=True,exist_ok=True)
    n=args.stages[0]
    grid=ordered(targets(n,n,args.roi,0.0),'snake')
    points=[dict(number=i+1,target_id=f'{n}x{n}_{p["id"]}',
                 tap_x=p['x'],tap_y=p['y']) for i,p in enumerate(grid)]
    plan={'schema':1,'roi':list(args.roi),'grid':n,'pattern':'snake','points':points}
    plan_file=args.out/'fast_snake_route.json'
    if plan_file.exists():
        if json.loads(plan_file.read_text(encoding='utf-8'))!=plan:
            raise RuntimeError('Route differs from saved session; use a new --out folder')
    else:
        save_json(plan_file,plan)
    state_file=args.out/'fast_snake_checkpoint.json'
    state=(json.loads(state_file.read_text(encoding='utf-8'))
           if state_file.exists() else {'schema':2,'attempted':[],'capture_sessions':[]})
    # Prior session format called attempts "completed"; do not repeat them blindly.
    attempted=set(state.get('attempted',[])) | set(state.get('completed',[]))
    pending=[p for p in points if p['target_id'] not in attempted]
    if args.max_clicks:
        pending=pending[:args.max_clicks]
    if not pending:
        print('[fast] No pending radar clicks; review saved captures for coverage.',flush=True)
        return

    load_adb_settings(args)
    ensure_adb_device(args)
    verify_device(args.adb,args.serial,args.roi)
    device=resolve_interface(args.dumpcap,args.interface)
    captures=args.out/'captures'
    captures.mkdir(exist_ok=True)
    players=load_players(args.out/'players.csv')
    session=datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
    prefix='continuous_'+session
    pcappath=captures/(prefix+'.pcapng')
    # Rotating files keep closed capture chunks readable if interrupted.
    cmd=[args.dumpcap,'-i',device,'-f','tcp port 9929',
         '-b','duration:10','-w',str(pcappath)]
    proc=None
    sent=[]
    failure=None
    started=time.monotonic()
    print(f'[fast] {n}x{n} top-left serpentine, {len(pending)} taps; '
          f'continuous capture; nominal interval {args.fast_interval:.2f}s; '
          f'checkpoint every {args.fast_batch} taps',flush=True)
    try:
        with (args.out/'dumpcap.log').open('a',encoding='utf-8') as log:
            proc=subprocess.Popen(cmd,stdout=subprocess.DEVNULL,stderr=log)
            time.sleep(.5)
            if proc.poll() is not None:
                raise RuntimeError('Wireshark capture did not start; see dumpcap.log')
            deadline=time.monotonic()
            for p in pending:
                if proc.poll() is not None:
                    raise RuntimeError('Wireshark stopped; refusing further unrecorded taps')
                # Never automatically retry an ambiguous ADB tap.
                adb_run(args.adb,args.serial,'shell','input','tap',
                        str(p['tap_x']),str(p['tap_y']),timeout=5)
                sent.append(p)
                state.setdefault('attempted',[]).append(p['target_id'])
                if len(sent)%args.fast_batch==0:
                    state['last_tap_utc']=datetime.now(timezone.utc).isoformat()
                    save_json(state_file,state)
                    print(f'[fast] {len(sent)}/{len(pending)} tapped; '
                          'capture still running (no batch pause)',flush=True)
                deadline+=args.fast_interval
                time.sleep(max(0,deadline-time.monotonic()))
            # Allow late map responses to arrive before terminating capture.
            time.sleep(1.2)
    except (KeyboardInterrupt,OSError,RuntimeError) as exc:
        failure=exc
        print(f'[fast] Tap sweep interrupted: {exc}; retaining recorded traffic',flush=True)
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        state['last_tap_utc']=datetime.now(timezone.utc).isoformat()
        save_json(state_file,state)

    files=sorted(captures.glob(prefix+'*.pcapng'),
                 key=lambda p:(p.stat().st_mtime_ns,p.name))
    if not files:
        raise RuntimeError('No PCAPNG files created; check dumpcap.log')
    views_seen=set()
    views_total=0
    decode_errors=0
    incoming=0
    records=[]
    # Decode only after the sweep: CPU/disk decoding never blocks radar taps.
    for i,file in enumerate(files):
        if file.stat().st_size<32:
            continue
        try:
            decoded,errors=decode_with_predecessor(
                file,files[i-1] if i else None,args.out)
            stats=traffic_stats(file)
            incoming+=stats['incoming_packets']
            decode_errors+=errors if isinstance(errors,int) else errors.get('decode_error',0)
            added=0
            for view,bases in decoded:
                sig=view_signature(view,bases)
                if sig in views_seen:
                    continue
                views_seen.add(sig)
                views_total+=1
                batch_players={}
                for player in bases:
                    key=player_key(player)
                    if key:
                        batch_players[key]=player
                if batch_players:
                    with connection(getattr(args,'history_db',
                                    Path('network_scans/player_history.sqlite3'))) as db:
                        ingest_records(db,batch_players.values(),str(file),
                                       observed_at=datetime.now(timezone.utc).isoformat())
                    before=len(players)
                    players.update(batch_players)
                    added+=len(players)-before
            save_csv(args.out/'players.csv',BASE_FIELDS,
                     sorted(players.values(),key=lambda p:player_key(p) or ''))
            records.append({'file':str(file),'decoded_views':len(decoded),
                            'new_players':added,'incoming_packets':stats['incoming_packets']})
        except (OSError,ValueError,EOFError,IndexError,KeyError) as exc:
            records.append({'file':str(file),'error':str(exc)})
            print(f'[fast] WARNING: cannot decode {file.name}: {exc}',flush=True)
    state.setdefault('capture_sessions',[]).append({
        'prefix':prefix,'attempted_taps':len(sent),'files':records,
        'decoded_unique_views':views_total,'incoming_packets':incoming,
        'decode_errors':decode_errors,'player_count':len(players),
        'duration_seconds':round(time.monotonic()-started,2),
        'finished_at_utc':datetime.now(timezone.utc).isoformat()})
    save_json(state_file,state)
    print(f'[fast] {len(sent)} taps, {len(files)} capture segments, '
          f'{views_total} unique decoded views, {len(players)} total bases; '
          f'{round(time.monotonic()-started,1)}s including decoding.',flush=True)
    if views_total==0:
        raise RuntimeError('No decoded map views; taps were attempted, not verified. '
                           'Review capture logs and map before another run.')
    if failure is not None:
        raise RuntimeError(f'Sweep interrupted after {len(sent)} taps; '
                           'saved capture and attempts for review') from failure
    print('[fast] Swept radar; individual taps and geographic completeness '
          'are not confirmed by batch network responses.',flush=True)
