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


# Calibrated from the player's 604x1080 home-city screenshot:
# center of the bottom-right "Leave City" button, in IMAGE fractions.
LEAVE_CITY_FRACTION=(0.907,0.954)


def leave_city_point(image, override=None):
    """Fixed lower-right city button; reject any top/right-side ad close tap."""
    h,w=image.shape[:2]
    point=coordinate(override if override is not None else
                     (round(w*LEAVE_CITY_FRACTION[0]),
                      round(h*LEAVE_CITY_FRACTION[1])),image)
    x,y=point
    if not (w*.72<=x<w and h*.85<=y<h):
        raise ValueError(
            f'Leave City target {point} is NOT in the bottom-right '
            f'of the {w}x{h} emulator screenshot. '
            'Refusing possible ad-close or stale map-button coordinate.')
    return point


def radar_template_match(image,template_path,roi=MINIMAP_ROI,threshold=.86):
    """Strict local OpenCV match; never infer radar from a generic minimap-looking area.

    For reliable results, the template should be a distinct STATIONARY radar UI
    border or icon crop, not changing terrain/player dots inside the radar.
    """
    import cv2
    template_path=Path(template_path)
    if not template_path.is_file():
        return False,0.0
    template=cv2.imread(str(template_path),cv2.IMREAD_GRAYSCALE)
    if template is None or template.size==0:
        raise ValueError(f'Radar reference unreadable: {template_path}')
    h,w=image.shape[:2]
    l,t,r,b=roi
    if not (0<=l<r<=w and 0<=t<b<=h):
        raise ValueError(f'Radar ROI {roi} outside emulator screenshot {w}x{h}')
    gray=cv2.cvtColor(image[t:b,l:r],cv2.COLOR_BGR2GRAY)
    th,tw=template.shape
    if th>gray.shape[0] or tw>gray.shape[1] or th<10 or tw<10:
        raise ValueError('Radar template crop must fit minimap ROI, minimum 10px')
    if float(template.std())<8:
        raise ValueError('Radar template is too featureless to identify safely')
    score=float(cv2.matchTemplate(gray,template,cv2.TM_CCOEFF_NORMED).max())
    return score>=threshold,score


def verify_radar(cfg,args,folder,label):
    """Read a current screenshot and locally test a previously calibrated radar crop."""
    image=read_screen(cfg)
    if not args.radar_template:
        save_screen(cfg,folder,label+'_needs_calibration',image)
        raise RuntimeError('Radar template not calibrated. No Ollama will run. '
                           'Save a cropped image of a stable radar UI feature, '
                           'then pass --radar-template PATH. Screenshot saved.')
    ready,score=radar_template_match(image,args.radar_template,args.roi,
                                     args.radar_threshold)
    print(f'[radar] Local template score {score:.3f}, required '
          f'{args.radar_threshold:.3f}',flush=True)
    return image,ready


def prepare_radar(cfg,args,folder):
    """Use Player Activity startup checks; fixed Leave City tap; local radar check."""
    import cv2
    from data_miner.startup import (run_ai_startup,popup_visible,
                                   promo_close_visible,city_label_visible)
    image=read_screen(cfg)
    save_screen(cfg,folder,'initial',image)
    save_status(folder,'startup_checks_no_ollama')
    print('Reusing login/ad handling, Ollama DISABLED for this pipeline.',flush=True)
    actions=run_ai_startup(cfg,max_actions=args.max_startup_actions,
                           allow_ai_fallback=False)
    save_status(folder,'city_ready',startup_actions=actions)
    image=read_screen(cfg)
    save_screen(cfg,folder,'city_after_popups',image)
    if popup_visible(image) or (promo_close_visible(image)
                                and not city_label_visible(image)):
        raise RuntimeError('Login/promo still visible; refusing to click Leave City')
    # The startup routine already requires a city confirmation; the tap itself
    # is fixed, avoiding another OCR pass or full-scene model inference.
    # Never use a possibly stale config.json map_button_tap: earlier
    # calibration may refer to the top-right UI, not Leave City.
    # Only an explicitly provided --map-tap may override this fixed button.
    point=leave_city_point(image,args.map_tap)
    h,w=image.shape[:2]
    print(f'[pipeline] Leave City: emulator screenshot {w}x{h}; '
          f'fixed bottom-right tap {point} '
          f'({point[0]/w:.1%} across, {point[1]/h:.1%} down). '
          'This is NOT the ad X in the top-right.',flush=True)
    save_status(folder,'leave_city_target_verified',
                map_tap=list(point),emulator_size=[w,h])
    one_tap(cfg,image,point,'Leave City (bottom-right)')
    save_status(folder,'leave_city_tapped',map_tap=list(point))
    time.sleep(1.1)
    after=read_screen(cfg)
    save_screen(cfg,folder,'after_leave_city',after)
    # A world map can contain gold X decorations and text OCR that falsely
    # resembles a promo or Leave City. Those generic detectors are intended
    # for city STARTUP only, not for deciding if a map transition succeeded.
    if popup_visible(after):
        raise RuntimeError('Login warning visible after Leave City; map not ready')
    if image.shape!=after.shape:
        raise RuntimeError('Emulator resolution changed after Leave City; cannot verify')
    # This only validates that the screen materially changed. It is not
    # sufficient to assert the radar is visible or scanning is safe.
    delta=float(sum(cv2.mean(cv2.absdiff(
        cv2.resize(image,(120,180)),cv2.resize(after,(120,180))))[:3])/3)
    print(f'[pipeline] City-to-world screen change: {delta:.2f}',flush=True)
    if delta<6:
        raise RuntimeError('Leave City tap did not visibly change the screen')
    save_status(folder,'world_screen_changed',screen_change=round(delta,2))
    if args.map_only:
        save_status(folder,'map_only_complete')
        print('LEAVE CITY COMPLETE. World screen saved. No zoom or scan performed.',
              flush=True)
        return

    # Radar recognition is a light-weight calibrated template match, NOT AI.
    # Do not zoom on unknown screens or begin the network scan without it.
    if not args.radar_template:
        save_status(folder,'radar_template_needed')
        raise RuntimeError('World map opened. To scan unattended without Ollama, '
                           'calibrate the fixed radar UI template via --radar-template. '
                           'No zoom or scan attempted.')
    image=after
    for step in range(args.max_zoom_actions+1):
        ready,score=radar_template_match(
            image,args.radar_template,args.roi,args.radar_threshold)
        print(f'[radar] check {step}: template score={score:.3f}',flush=True)
        if ready:
            repeat=read_screen(cfg)
            second,score2=radar_template_match(
                repeat,args.radar_template,args.roi,args.radar_threshold)
            if second:
                save_screen(cfg,folder,'radar_verified',repeat)
                save_status(folder,'radar_verified',zoom_actions=step,
                            radar_score=round(score2,3))
                return
        if step==args.max_zoom_actions:
            break
        if args.zoom_method=='bluestacks':
            from bluestacks_zoom import zoom_out_ctrl_minus
            zoom_out_ctrl_minus(args.zoom_hold)
        else:
            point=args.zoom_tap or (cfg.get('ui',{}).get('world_map',{}) or {}).get('zoom_out_tap')
            if args.zoom_method=='tap':
                if point is None:
                    raise RuntimeError('Zoom tap not calibrated; pass --zoom-tap X Y')
                one_tap(cfg,image,point,f'Zoom out {step+1}')
            elif args.zoom_method=='keyevent':
                from scanner import adb
                if args.zoom_keyevent is None or not 1<=args.zoom_keyevent<=300:
                    raise ValueError('Set a verified --zoom-keyevent between 1 and 300')
                adb(cfg,'shell','input','keyevent',str(args.zoom_keyevent))
            else:
                raise ValueError('Unknown zoom method: '+str(args.zoom_method))
        time.sleep(args.zoom_delay)
        image=read_screen(cfg)
        if popup_visible(image) or promo_close_visible(image):
            save_screen(cfg,folder,'unexpected_overlay',image)
            raise RuntimeError('Unexpected popup during zoom; stopping safely')
    save_screen(cfg,folder,'radar_not_verified',image)
    raise RuntimeError('Radar not verified within bounded zoom actions; scan not started')


def zoom_probe(cfg,args,folder):
    """One or a few controlled zoom attempts on an ALREADY OPEN world map.

    Does not run startup, touch the city navigation, detect the radar, or scan.
    The caller explicitly confirms the world map is open by using --zoom-only.
    """
    import cv2
    from bluestacks_zoom import zoom_out_ctrl_minus
    from data_miner.startup import popup_visible
    before=read_screen(cfg)
    save_screen(cfg,folder,'zoom_before',before)
    if popup_visible(before):
        raise RuntimeError('Login warning is visible; zoom not sent')
    if args.zoom_steps != 1:
        raise ValueError('BlueStacks zoom-only performs exactly one held Ctrl+- action; set --zoom-steps 1')
    print(f'[zoom] One Ctrl+- hold for {args.zoom_hold:.1f}s; no additional zoom actions.',flush=True)
    save_status(folder,'zoom_probe_started',zoom_steps=args.zoom_steps,
                method='bluestacks_ctrl_minus',hold_seconds=args.zoom_hold)
    for step in range(1,args.zoom_steps+1):
        print(f'[zoom] Holding BlueStacks Ctrl+- for {args.zoom_hold:.1f}s '
              f'({step}/{args.zoom_steps}); no Ollama or scan',flush=True)
        zoom_out_ctrl_minus(args.zoom_hold)
        time.sleep(max(0.65,args.zoom_delay))
        after=read_screen(cfg)
        save_screen(cfg,folder,f'zoom_after_{step}',after)
        if before.shape!=after.shape:
            raise RuntimeError('Screen resolution changed during zoom; inspect screenshots')
        h,w=before.shape[:2]
        # Compare the center of the game map, not static sidebars or moving timers.
        y0,y1=round(h*.22),round(h*.78)
        x0,x1=round(w*.18),round(w*.82)
        first=cv2.resize(before[y0:y1,x0:x1],(180,180))
        second=cv2.resize(after[y0:y1,x0:x1],(180,180))
        diff=float(sum(cv2.mean(cv2.absdiff(first,second))[:3])/3)
        print(f'[zoom] Center-map visual difference: {diff:.2f}',flush=True)
        save_status(folder,'zoom_probe_step',zoom_step=step,
                    visual_change=round(diff,2))
        if diff<3:
            print('[zoom] Little visible change; stopping zoom attempts. '
                  'Check BlueStacks Game controls > Zoom mapping/Override.',
                  flush=True)
            break
        before=after
    save_status(folder,'zoom_probe_complete')
    print('ZOOM PROBE COMPLETE: check zoom_before.png and zoom_after_*.png. '
          'Radar readiness has NOT been verified, and no scan started.',
          flush=True)


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
                       help='Override fixed bottom-right Leave City tap center in emulator pixels')
        a.add_argument('--zoom-tap',type=int,nargs=2,metavar=('X','Y'),
                       help='Manually VERIFIED minus / zoom-out button center')
        a.add_argument('--zoom-keyevent',type=int,
                       help='Verified Android keycode mapped to zoom-out, if no button exists')
        a.add_argument('--zoom-method',choices=('bluestacks','tap','keyevent'),
                       default='bluestacks',
                       help='When radar template is configured: zoom via BlueStacks Ctrl+-, tapped control, or Android keycode')
        a.add_argument('--max-zoom-actions',type=int,default=1,
                       help='Maximum radar zoom actions; default 1 for BlueStacks safety')
        a.add_argument('--zoom-delay',type=float,default=.6)
        a.add_argument('--zoom-hold',type=float,default=3.0,
                       help='Continuous BlueStacks Ctrl+- key hold, 3–5 seconds (default 3)')
        a.add_argument('--max-startup-actions',type=int,default=12)
        a.add_argument('--execute',action='store_true')
        a.add_argument('--map-only',action='store_true',
                       help='Stop after fixed Leave City tap; no zoom or network scan')
        a.add_argument('--zoom-only',action='store_true',
                       help='Assume world map is already open; test BlueStacks zoom out and save screenshots, no scan')
        a.add_argument('--zoom-steps',type=int,default=1,
                       help='Zoom attempts in zoom-only probe (must be 1 for BlueStacks)')
        a.add_argument('--radar-template',type=Path,
                       help='Local cropped radar UI reference PNG for OpenCV matching')
        a.add_argument('--radar-threshold',type=float,default=.86)
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
    if not 3.0<=args.zoom_hold<=5.0:
        p.error('--zoom-hold must be between 3.0 and 5.0 seconds')
    if args.zoom_steps!=1:
        p.error('--zoom-steps must be exactly 1; repeated BlueStacks holds reset zoom')
    if args.zoom_method=='bluestacks' and args.max_zoom_actions!=1:
        p.error('BlueStacks zoom permits only one automatic hold; use --max-zoom-actions 1')
    if args.max_zoom_actions<1 or args.max_zoom_actions>30 or not .2<=args.zoom_delay<=4:
        p.error('Zoom limits invalid')
    if not .6<=args.radar_threshold<=.99:
        p.error('--radar-threshold must be between 0.6 and 0.99')
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
        print('Ollama-free: fixed bottom-right Leave City; radar requires cropped OpenCV template.')
        print(f'Zoom uses one continuous Ctrl+- hold for {args.zoom_hold:.1f}s, not repeated key taps.')
        print('Start: confirm login -> dismiss promotions -> Leave City -> zoom to radar')
        print('Then: passive scan '+str(args.stages)+' '+args.pattern+
              ' ; player names stored in '+str(ROOT/'player_history.sqlite3'))
        return
    from pattern_benchmark import ensure_adb_device
    ensure_adb_device(SimpleNamespace(adb=cfg['adb_path'],serial=cfg['adb_serial']))
    try:
        if args.command=='inspect':
            from data_miner.startup import popup_visible,promo_close_visible,city_label_visible
            image=read_screen(cfg)
            save_screen(cfg,folder,'startup_inspect',image)
            screen=('login_warning' if popup_visible(image) else
                    'promotion' if promo_close_visible(image) else
                    'city' if city_label_visible(image) else 'unrecognized')
            save_status(folder,'inspection_complete',screen=screen)
            print('READ ONLY (no Ollama): screen='+screen,flush=True)
            return
        save_status(folder,'started',server=args.server,
                    history_db=str(ROOT/'player_history.sqlite3'))
        if args.zoom_only:
            zoom_probe(cfg,args,folder)
            return
        if args.startup_only:
            from data_miner.startup import run_ai_startup
            save_status(folder,'reusing_player_activity_startup')
            actions=run_ai_startup(cfg,max_actions=args.max_startup_actions,
                               allow_ai_fallback=False)
            save_status(folder,'startup_complete',startup_actions=actions)
            save_screen(cfg,folder,'city_after_startup',read_screen(cfg))
            print('STARTUP COMPLETE: city verified by Player Activity handler. '
                  'No map or network scan attempted.',flush=True)
            return
        prepare_radar(cfg,args,folder)
        if args.map_only:
            return
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
