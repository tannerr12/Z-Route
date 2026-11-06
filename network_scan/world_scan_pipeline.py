#!/usr/bin/env python3
"""Verified Z-Route startup -> Leave City -> radar -> passive network scan.

From the repository root:
  python network_scan/world_scan_pipeline.py inspect
  python network_scan/world_scan_pipeline.py run --execute --prepare-only
  python network_scan/world_scan_pipeline.py run --execute --max-clicks 4
  python network_scan/world_scan_pipeline.py run --execute

This pipeline REUSES data_miner.startup.run_ai_startup() from
 data_miner/player_activity.py for login confirmation and advertisements.
It does not implement another popup handler.

This pipeline does not know your emulator's map/zoom button locations until
they are detected on an actual screenshot or explicitly calibrated. Unknown
screens and absent radar verification STOP, not trigger speculative taps.
Full scans use the existing network decoder; observations enter the shared
private SQLite name-history database before each click is checkpointed.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

REPO=Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0,str(REPO))

ROOT=Path('network_scans')
SCAN_ROOT=ROOT/'map_refresh'
MINIMAP_ROI=(800,25,1060,270)  # Prior successful 1080x1920 calibration.
CONFIDENCE=.85


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def new_folder():
    return SCAN_ROOT/datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')


def save_status(folder, phase, **details):
    folder.mkdir(parents=True,exist_ok=True)
    path=folder/'pipeline_status.json'
    previous={}
    if path.exists():
        try:previous=json.loads(path.read_text(encoding='utf-8'))
        except (OSError,ValueError):pass
    previous.update(phase=phase,updated_at_utc=timestamp(),**details)
    tmp=path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(previous,indent=2,ensure_ascii=False),encoding='utf-8')
    tmp.replace(path)
    print(f'[pipeline] {phase}',flush=True)
    return previous


def save_screen(cfg,folder,label,image):
    from scanner import save_capture_png
    folder.mkdir(parents=True,exist_ok=True)
    path=folder/(label+'.png')
    save_capture_png(cfg,path,image)
    print(f'  Screenshot: {path}',flush=True)
    return path


def read_screen(cfg,attempts=3):
    """Retry READ-ONLY screenshots across recoverable ADB disconnects.

    Never retry a timed-out tap: it may already have been executed.
    """
    from scanner import screenshot, ensure_game_connected
    from pattern_benchmark import ensure_adb_device
    for i in range(attempts):
        try:
            image=screenshot(cfg)
            ensure_game_connected(cfg,image)
            return image
        except (OSError,RuntimeError) as exc:
            # Connection-lost game dialogs are not transient ADB errors.
            if 'connection lost' in str(exc).casefold():
                raise
            if i==attempts-1:
                raise RuntimeError(f'Unable to capture verified game screen: {exc}') from exc
            print(f'  Read-only screenshot retry {i+1}/{attempts}: {exc}',flush=True)
            settings=SimpleNamespace(adb=cfg.get('adb_path') or 'adb',
                                     serial=cfg.get('adb_serial') or '127.0.0.1:5555')
            ensure_adb_device(settings)
            time.sleep(.4*(i+1))
    raise RuntimeError('Screenshot unavailable')


def coordinate(point,image):
    """Validate a calibrated emulator-image pixel coordinate."""
    if not isinstance(point,(tuple,list)) or len(point)!=2:
        raise ValueError('Expected a two-integer emulator screenshot coordinate')
    x,y=point
    if any(isinstance(n,bool) or not isinstance(n,(int,float)) or int(n)!=n
           for n in (x,y)):
        raise ValueError('Expected integer emulator screenshot coordinates')
    h,w=image.shape[:2]
    if not (0<=x<w and 0<=y<h):
        raise ValueError(f'Tap ({x},{y}) outside emulator screenshot {w}x{h}')
    return int(x),int(y)


def one_tap(cfg,image,point,what):
    from scanner import adb
    x,y=coordinate(point,image)
    print(f'  {what}: tapping emulator ({x},{y}) once',flush=True)
    # A timed-out ADB tap has unknown delivery; do not blindly repeat.
    adb(cfg,'shell','input','tap',str(x),str(y))


def confidence(data,flag,minimum=CONFIDENCE):
    conf=data.get('confidence',0)
    return data.get(flag) is True and isinstance(conf,(float,int)) and not isinstance(conf,bool) and minimum<=conf<=1


def radar_box_valid(box,image,roi=MINIMAP_ROI):
    """A positive AI answer must actually locate radar within calibrated ROI."""
    if not isinstance(box,(list,tuple)) or len(box)!=4:
        return False
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) for v in box):
        return False
    h,w=image.shape[:2]
    x1,y1,x2,y2=box
    if not (0<=x1<x2<=w and 0<=y1<y2<=h):
        return False
    cx,cy=(x1+x2)/2,(y1+y2)/2
    left,top,right,bottom=roi
    return (left<=cx<=right and top<=cy<=bottom and
            x2-x1>=25 and y2-y1>=25)


def vision_world(cfg,image,roi=MINIMAP_ROI):
    from data_miner.target_locator import ask_vision
    result=ask_vision(cfg,image,
        "Inspect the actual Z-Route screenshot, not an expected workflow. "
        "Return JSON with world_map boolean, radar_visible boolean, "
        "confidence number 0..1, radar_box array [x1,y1,x2,y2] or null. "
        "world_map means the outdoor WORLD MAP with bases/world X-Y, not the "
        "home city or a promotion. radar_visible means the clickable small "
        "overview RADAR / MINIMAP in the TOP RIGHT that appears at the "
        "appropriate zoom, NOT a decorative icon or ordinary base. "
        "If uncertain return false and null. Do not guess coordinates.",
        max_tokens=350,retries=1)
    map_ok=confidence(result,'world_map',.8)
    radar_ok=(map_ok and confidence(result,'radar_visible') and
              radar_box_valid(result.get('radar_box'),image,roi))
    return map_ok,radar_ok,result


def locate_city_map(cfg,image):
    from data_miner.target_locator import locate_text_button
    return locate_text_button(cfg,image,
        target='Leave City (the city-screen button that opens the world map)',
        context='Z-Route HOME CITY screen after login and promotions. Locate the actual button labeled Leave City; do not click Alliance, Explore, or a base.')


def locate_zoom_out(cfg,image):
    from data_miner.target_locator import locate_text_button
    return locate_text_button(cfg,image,
        target='Zoom OUT / minus (-) button for world map zoom (not a plus button, base or other icon)',
        context='Z-Route WORLD MAP screen with map controls, where radar has not appeared yet.')


def configured_tap(cfg,cli,config_name):
    if cli is not None:return cli
    return (cfg.get('ui',{}).get('world_map',{}) or {}).get(config_name)


def verify_world_after_map(cfg,folder,roi,max_checks=4):
    for i in range(max_checks):
        image=read_screen(cfg)
        save_screen(cfg,folder,'map_after_open_'+str(i),image)
        world,radar,result=vision_world(cfg,image,roi)
        if world:
            return image,radar
        if i!=max_checks-1:
            time.sleep(.85)
    raise RuntimeError('Map button was tapped but WORLD MAP was never verified; no zoom attempted')


def prepare_radar(cfg,args,folder):
    # Exactly the same proven startup path used by data_miner.player_activity.
    # IMPORTANT: a login warning MUST be handled before calling Ollama.
    # The modal can remain on-screen while a slow world-map inference waits.
    from data_miner.startup import run_ai_startup, popup_visible
    from data_miner.vision import classify_screen
    image=read_screen(cfg)
    save_screen(cfg,folder,'initial',image)
    print('[pipeline] Checking login warning locally before any Ollama call...',flush=True)
    if popup_visible(image):
        save_status(folder,'login_warning_detected')
        print('Login warning visible: going directly to the existing '
              'Player Activity confirmation handler, no world-map AI first.',
              flush=True)
        world,radar=False,False
    else:
        save_status(folder,'checking_already_open_world_map')
        world,radar,_=vision_world(cfg,image,args.roi)
    if not world:
        save_status(folder,'reusing_player_activity_startup')
        actions=run_ai_startup(cfg,max_actions=args.max_startup_actions)
        save_status(folder,'city_verified',startup_actions=actions)
        image=read_screen(cfg)
        save_screen(cfg,folder,'city_after_popups',image)
        screen,conf=classify_screen(cfg,image)
        if screen!='city' or conf<.8:
            raise RuntimeError(f'Expected verified city after login/ads, got {screen} ({conf:.2f})')
        target=configured_tap(cfg,args.map_tap,'map_button_tap')
        if target is None:
            try:target=locate_city_map(cfg,image)
            except (RuntimeError,ValueError) as exc:
                raise RuntimeError('Cannot confidently locate Leave City. Calibrate --map-tap X,Y '
                                   'using city_after_popups.png (emulator pixels).') from exc
        one_tap(cfg,image,target,'Leave City / open world map')
        save_status(folder,'map_tapped',map_tap=list(target))
        time.sleep(.9)
        image,radar=verify_world_after_map(cfg,folder,args.roi)
    else:
        save_status(folder,'world_map_verified',radar_already_visible=radar)
    if radar:
        # Confirm a second independent screen before scanning.
        image=read_screen(cfg)
        _,radar,_=vision_world(cfg,image,args.roi)
        if not radar:
            raise RuntimeError('Radar verification unstable; no scan initiated')
        save_screen(cfg,folder,'radar_verified',image)
        save_status(folder,'radar_verified',zoom_actions=0)
        return

    save_status(folder,'zoom_to_radar')
    for step in range(args.max_zoom_actions):
        image=read_screen(cfg)
        world,radar,_=vision_world(cfg,image,args.roi)
        if not world:
            save_screen(cfg,folder,'lost_world_map',image)
            raise RuntimeError('World map no longer visible; stopped before next zoom input')
        if radar:
            repeat=read_screen(cfg)
            _,repeat_ok,_=vision_world(cfg,repeat,args.roi)
            if not repeat_ok:
                raise RuntimeError('Radar appeared only in one vision reading; stopped')
            save_screen(cfg,folder,'radar_verified',repeat)
            save_status(folder,'radar_verified',zoom_actions=step)
            return

        point=configured_tap(cfg,args.zoom_tap,'zoom_out_tap')
        key=args.zoom_keyevent
        if point is None and key is None:
            try:point=locate_zoom_out(cfg,image)
            except (RuntimeError,ValueError) as exc:
                save_screen(cfg,folder,'zoom_control_unverified',image)
                raise RuntimeError('Zoom-out control could not be verified. Supply '
                                   '--zoom-tap X,Y for a VERIFIED zoom-out button, '
                                   'or --zoom-keyevent CODE if you verified the '
                                   'BlueStacks zoom key. No blind zoom.') from exc
        if point is not None:
            one_tap(cfg,image,point,f'Zoom out {step+1}')
        else:
            from scanner import adb
            if not isinstance(key,int) or not (1<=key<=300):
                raise ValueError('Invalid verified Android zoom keycode')
            print(f'  Verified zoom keyevent {key}, action {step+1}',flush=True)
            adb(cfg,'shell','input','keyevent',str(key))
        time.sleep(args.zoom_delay)
    image=read_screen(cfg)
    world,radar,_=vision_world(cfg,image,args.roi)
    if world and radar:
        repeat=read_screen(cfg)
        _,repeat_ok,_=vision_world(cfg,repeat,args.roi)
        if repeat_ok:
            save_screen(cfg,folder,'radar_verified',repeat)
            save_status(folder,'radar_verified',zoom_actions=args.max_zoom_actions)
            return
    save_screen(cfg,folder,'radar_not_found',image)
    raise RuntimeError(f'Radar not confirmed after {args.max_zoom_actions} zoom actions; scan NOT started')


def baseline(out,chosen=None):
    if chosen is not None:
        return chosen if chosen.is_file() else None
    folders=sorted((p for p in SCAN_ROOT.glob('*/players.csv')
                    if p.is_file() and p.parent!=out),key=lambda p:p.stat().st_mtime,reverse=True)
    if folders:return folders[0]
    candidate=ROOT/'full_map'/'players.csv'
    return candidate if candidate.is_file() else None


def run_scan(args,folder):
    from full_map_scan import scan
    state=SimpleNamespace(
        roi=list(args.roi),stages=args.stages,pattern=args.pattern,
        inset=.07,min_separation=8,out=folder,
        history_db=ROOT/'player_history.sqlite3',
        interface=args.interface,dumpcap=args.dumpcap,
        adb=None,serial=None,seconds=args.seconds,retry_extra=3,
        retries=args.retries,goal=args.goal,stop_at_goal=False,
        retry_review=False,max_clicks=args.max_clicks,execute=True)
    save_status(folder,'network_scanning',
                scan_pattern=args.pattern,scan_stages=args.stages,
                max_clicks=args.max_clicks)
    scan(state)
    state_file=folder/'checkpoint.json'
    if not state_file.is_file():
        raise RuntimeError('No scanner checkpoint recorded; network scanning did not complete')
    record=json.loads(state_file.read_text(encoding='utf-8'))
    entries=record.get('entries',[])
    good=sum(entry.get('status') in ('OK','OVERLAP','EMPTY') for entry in entries)
    if good==0:
        raise RuntimeError('No confirmed decoded map captures. Examine dumpcap.log and captured PCAPs.')
    save_status(folder,'network_scan_recorded',
                successful_clicks=good,all_click_results=len(entries),
                roster=str(folder/'players.csv'))


def report_changes(args,folder):
    from player_history import connection, export_renames, sync
    with connection(ROOT/'player_history.sqlite3') as history:
        sync(history,ROOT)
        export_renames(history,folder/'all_name_changes.csv',str(args.server))
    prior=baseline(folder,args.before)
    current=folder/'players.csv'
    if prior and current.is_file():
        from scan_changes import run
        run(SimpleNamespace(before=prior,after=current,
                            out=folder/'changes_from_previous',
                            server=args.server,network_root=ROOT,
                            history_db=ROOT/'player_history.sqlite3'))
        save_status(folder,'comparison_saved',compared_against=str(prior))
    else:
        print('No earlier roster found; lifetime rename history exported.',flush=True)


def cli():
    p=argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub=p.add_subparsers(dest='command',required=True)
    for command in ('inspect','run'):
        a=sub.add_parser(command,help='Read-only screenshot diagnostic' if command=='inspect'
                         else 'Verified startup and optional passive world scan')
        a.add_argument('--out',type=Path,help='New session folder; defaults to timestamped map_refresh path')
        a.add_argument('--roi',type=str,default='800,25,1060,270',
                       help='Previously calibrated radar ROI as emulator L,T,R,B')
        a.add_argument('--map-tap',type=int,nargs=2,metavar=('X','Y'),
                       help='Manually VERIFIED View Map button center in emulator pixels')
        a.add_argument('--zoom-tap',type=int,nargs=2,metavar=('X','Y'),
                       help='Manually VERIFIED minus / zoom-out button center')
        a.add_argument('--zoom-keyevent',type=int,
                       help='Verified Android keycode mapped to zoom-out, if no button exists')
        a.add_argument('--max-zoom-actions',type=int,default=12)
        a.add_argument('--zoom-delay',type=float,default=.6)
        a.add_argument('--max-startup-actions',type=int,default=12)
        a.add_argument('--execute',action='store_true')
        a.add_argument('--prepare-only',action='store_true',
                       help='Stop immediately after radar verified; do not network-scan')
        a.add_argument('--startup-only',action='store_true',
                       help='Reuse Player Activity login confirmation and ad closing only; skip map and scan')
        a.add_argument('--pattern',choices=('spread','spiral','snake','checkerboard'),default='spread')
        a.add_argument('--stages',type=str,default='4,7,10')
        a.add_argument('--max-clicks',type=int,default=0,
                       help='Limit network-scan clicks for pilot; 0 scans all')
        a.add_argument('--seconds',type=int,default=4)
        a.add_argument('--retries',type=int,default=2)
        a.add_argument('--goal',type=int,default=9500)
        a.add_argument('--server',type=int,default=125)
        a.add_argument('--interface',default='Wi-Fi')
        a.add_argument('--dumpcap',default=r'C:\Program Files\Wireshark\dumpcap.exe')
        a.add_argument('--before',type=Path,help='Prior exact-world players.csv to compare with')
    args=p.parse_args()
    from pattern_benchmark import parse_roi
    args.roi=parse_roi(args.roi)
    try:args.stages=[int(v.strip()) for v in args.stages.split(',')]
    except ValueError as exc:p.error('Stages must be comma-separated numbers')
    if (not args.stages or args.stages!=sorted(set(args.stages)) or
        any(not 2<=v<=25 for v in args.stages)):
        p.error('Stages must be strictly increasing grid sizes between 2 and 25')
    if args.max_zoom_actions<1 or args.max_zoom_actions>30 or not .2<=args.zoom_delay<=4:
        p.error('Zoom limits invalid')
    if args.max_startup_actions<1 or args.max_startup_actions>30 or args.max_clicks<0:
        p.error('Startup/click limit invalid')
    if not 3<=args.seconds<=30 or not 1<=args.retries<=5:
        p.error('Capture interval/retries invalid')
    if args.goal<1 or args.server<1:
        p.error('Invalid goal/server')
    if args.command=='inspect':
        args.execute=False
    folder=args.out or new_folder()
    from scanner import load_config
    cfg=load_config()
    # The driver cannot safely use device settings different from scan().
    cfg.setdefault('adb_path','adb')
    cfg.setdefault('adb_serial','127.0.0.1:5555')
    if args.command=='run' and not args.execute:
        print('PREVIEW ONLY: no input to game. To navigate, add --execute.')
        print('Start: confirm login -> dismiss promotions -> Leave City -> zoom to radar')
        print('Then: passive scan '+str(args.stages)+' '+args.pattern+
              ' ; player names stored in '+str(ROOT/'player_history.sqlite3'))
        return
    from pattern_benchmark import ensure_adb_device
    ensure_adb_device(SimpleNamespace(adb=cfg['adb_path'],serial=cfg['adb_serial']))
    try:
        if args.command=='inspect':
            from data_miner.startup import popup_visible
            image=read_screen(cfg)
            save_screen(cfg,folder,'startup_inspect',image)
            if popup_visible(image):
                save_status(folder,'inspection_complete',screen='login_warning',
                            world_map=False,radar_verified=False)
                print('READ ONLY: login warning detected; use run --execute '
                      '--startup-only for existing Confirm/ad workflow',flush=True)
                return
            world,radar,result=vision_world(cfg,image,args.roi)
            save_status(folder,'inspection_complete',world_map=world,
                        radar_verified=radar,raw_radar_detection=result)
            print('READ ONLY — no clicks; inspect screenshot and diagnostics')
            return
        save_status(folder,'started',server=args.server,
                    history_db=str(ROOT/'player_history.sqlite3'))
        if args.startup_only:
            from data_miner.startup import run_ai_startup
            save_status(folder,'reusing_player_activity_startup')
            actions=run_ai_startup(cfg,max_actions=args.max_startup_actions)
            save_status(folder,'startup_complete',startup_actions=actions)
            save_screen(cfg,folder,'city_after_startup',read_screen(cfg))
            print('STARTUP COMPLETE: city verified by Player Activity handler. '
                  'No map or network scan attempted.',flush=True)
            return
        prepare_radar(cfg,args,folder)
        if args.prepare_only:
            save_status(folder,'prepared_no_scan')
            print('RADAR READY. No network scanning requested.',flush=True)
            return
        run_scan(args,folder)
        report_changes(args,folder)
        save_status(folder,'complete')
        print('Pipeline completed. Private data:',folder,flush=True)
    except (RuntimeError,ValueError,OSError,TimeoutError) as exc:
        save_status(folder,'failed',error=str(exc))
        print(f'PIPELINE STOPPED SAFELY: {exc}',file=sys.stderr,flush=True)
        print('Inspect diagnostics in:',folder,file=sys.stderr,flush=True)
        raise SystemExit(1) from exc


if __name__=='__main__':
    cli()
