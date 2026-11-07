#!/usr/bin/env python3
"""Fast, dense, top-left serpentine minimap sweep with batched passive captures.

Each batch is recorded BEFORE the first tap. Tap spacing is nominally 0.70s;
ADB can make physical intervals longer. A decoded batch validates traffic, NOT
each individual tapped location. All PCAPs and attempted taps are retained.
"""
from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from full_map_scan import load_players, player_key
from live_watch import resolve_interface, traffic_stats
from pattern_benchmark import (adb_run, ensure_adb_device, load_adb_settings,
                               ordered, targets, verify_device)
from player_history import connection, ingest_records
from scan import BASE_FIELDS, inspect, save_csv


def save_json(path, obj):
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(obj,indent=2,ensure_ascii=False),encoding='utf-8')
    temp.replace(path)


def fast_scan(args):
    """Scan one dense grid. Resume using --out and the same exact configuration."""
    if args.pattern!='snake' or len(args.stages)!=1:
        raise ValueError('Fast sweep requires --pattern snake and one --stages grid size')
    if not .5<=args.fast_interval<1 or not 2<=args.fast_batch<=20:
        raise ValueError('Fast settings: interval 0.5..0.99 seconds; batch 2..20 taps')
    args.out.mkdir(parents=True,exist_ok=True)
    n=args.stages[0]
    all_points=ordered(targets(n,n,args.roi,.07),'snake')
    points=[dict(number=i+1, target_id=f'{n}x{n}_{p["id"]}',
                 tap_x=p['x'],tap_y=p['y']) for i,p in enumerate(all_points)]
    plan={'schema':1,'roi':list(args.roi),'grid':n,'pattern':'snake','points':points}
    plan_file=args.out/'fast_snake_route.json'
    if plan_file.exists():
        old=json.loads(plan_file.read_text(encoding='utf-8'))
        if old!=plan:
            raise RuntimeError('Existing fast-snake output uses a different route; choose new --out')
    else:
        save_json(plan_file,plan)
    state_file=args.out/'fast_snake_checkpoint.json'
    state=(json.loads(state_file.read_text(encoding='utf-8'))
           if state_file.exists() else {'schema':1,'completed':[],'batches':[]})
    finished=set(state['completed'])
    pending=[p for p in points if p['target_id'] not in finished]
    if args.max_clicks:
        pending=pending[:args.max_clicks]
    if not pending:
        print('[fast] No pending minimap taps.',flush=True)
        return
    load_adb_settings(args)
    ensure_adb_device(args)
    verify_device(args.adb,args.serial,args.roi)
    device=resolve_interface(args.dumpcap,args.interface)
    captures=args.out/'captures'
    captures.mkdir(exist_ok=True)
    players=load_players(args.out/'players.csv')
    unconfirmed=0
    print(f'[fast] Dense {n}x{n} grid, top-left serpentine; '
          f'{len(pending)} remaining taps; nominal spacing {args.fast_interval:.2f}s',flush=True)
    for start in range(0,len(pending),args.fast_batch):
        group=pending[start:start+args.fast_batch]
        batch_id=len(state['batches'])+1
        capture=captures/f'fast_snake_{batch_id:04d}.pcapng'
        # A small initial margin plus a bounded period after the last input.
        duration=max(4, int(len(group)*args.fast_interval+4.5))
        cmd=[args.dumpcap,'-i',device,'-f','tcp port 9929',
             '-a',f'duration:{duration}','-w',str(capture)]
        sent=[]
        proc=None
        log_file=args.out/'dumpcap.log'
        try:
            with log_file.open('a',encoding='utf-8') as log:
                proc=subprocess.Popen(cmd,stdout=subprocess.DEVNULL,stderr=log)
                time.sleep(.45)
                if proc.poll() is not None:
                    raise RuntimeError('dumpcap exited before taps; see dumpcap.log')
                deadline=time.monotonic()
                for p in group:
                    if proc.poll() is not None:
                        raise RuntimeError('dumpcap stopped during taps; refusing unrecorded clicks')
                    adb_run(args.adb,args.serial,'shell','input','tap',
                            str(p['tap_x']),str(p['tap_y']),timeout=5)
                    sent.append(p)
                    print(f'[fast] Tap {p["number"]}/{len(points)} '
                          f'({p["tap_x"]},{p["tap_y"]})',flush=True)
                    deadline+=args.fast_interval
                    time.sleep(max(0,deadline-time.monotonic()))
                proc.wait(timeout=duration+15)
                if proc.returncode!=0:
                    raise RuntimeError('dumpcap failed; inspect dumpcap.log')
            views,errors=inspect(capture)
            traffic=traffic_stats(capture)
            observed={}
            for view,bases in views:
                for player in bases:
                    key=player_key(player)
                    if key:
                        observed[key]=player
            # History must be durable before checkpointing completed attempts.
            if observed:
                with connection(getattr(args,'history_db',Path('network_scans/player_history.sqlite3'))) as db:
                    ingest_records(db,observed.values(),str(capture),
                                   observed_at=datetime.now(timezone.utc).isoformat())
            count_before=len(players)
            players.update(observed)
            save_csv(args.out/'players.csv',BASE_FIELDS,
                     sorted(players.values(),key=lambda p:player_key(p) or ''))
            confirmed=bool(views)
            state['batches'].append(dict(batch=batch_id,
                target_ids=[p['target_id'] for p in sent],
                capture=str(capture),map_views=len(views),
                incoming_packets=traffic['incoming_packets'],
                new_players=len(players)-count_before,
                unique_players=len(players),decode_errors=errors,
                status='MAP_RESPONSE' if confirmed else 'UNCONFIRMED',
                updated_at=datetime.now(timezone.utc).isoformat()))
            if confirmed:
                state['completed'].extend(p['target_id'] for p in sent)
            save_json(state_file,state)
            unconfirmed=0 if confirmed else unconfirmed+1
            print(f'[fast] Batch {batch_id}: {len(views)} decoded views, '
                  f'+{len(players)-count_before} new, {len(players)} total; '
                  f'{len(state["completed"])} confirmed-batch taps, '
                  f'{len(sent)} taps in this batch (no per-tap validation)',flush=True)
            if unconfirmed>=3:
                print('[fast] STOP: three consecutive batches with no decoded map responses. '
                      'Inspect PCAPs, adapter, zoom and map before resuming.',flush=True)
                raise RuntimeError('Three batches had no decoded map response')
        except (OSError,RuntimeError,subprocess.TimeoutExpired) as exc:
            # Unknown ADB tap delivery must never be retried automatically.
            print(f'[fast] STOP: {exc}; capture and checkpoint retained. '
                  'Do not assume the last tap was delivered.',flush=True)
            raise RuntimeError('Fast sweep stopped; inspect last batch before resuming') from exc
        finally:
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:proc.wait(timeout=6)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
    print(f'[fast] Finished attempted sweep: {len(points)} planned, '
          f'{len(state["completed"])} tapped, {len(players)} unique bases. '
          'Batch response confirmation is not geographic coverage proof.',flush=True)
