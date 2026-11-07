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
import subprocess
import sys
from contextlib import contextmanager
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
        raise FileNotFoundError(
            f'Radar reference PNG not found: {template_path}. '
            'The radar may be visible in BlueStacks, but the scanner '
            'needs a cropped stationary UI reference. '
            'Use the saved radar_not_verified.png to calibrate one.')
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



@contextmanager
def initial_world_capture(args, folder):
    """Capture the first world load before the Leave City tap."""
    from live_watch import resolve_interface
    from scan import inspect, save_csv, BASE_FIELDS
    from full_map_scan import player_key
    from player_history import connection, ingest_records

    output=folder/'initial_world_load.pcapng'
    device=resolve_interface(args.dumpcap,args.interface)
    command=[args.dumpcap,'-i',device,'-f','tcp port 9929',
             '-a','duration:15','-w',str(output)]
    with (folder/'dumpcap.log').open('a',encoding='utf-8') as log:
        proc=subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=log)
        try:
            time.sleep(.5)
            if proc.poll() is not None:
                raise RuntimeError('Initial Wireshark capture failed to start; see dumpcap.log')
            save_status(folder,'initial_capture_active',initial_capture=str(output))
            print('[capture] Wireshark active BEFORE Leave City tap',flush=True)
            yield
            proc.wait(timeout=20)
            if proc.returncode!=0:
                raise RuntimeError('Initial Wireshark capture failed; see dumpcap.log')
            views,failures=inspect(output)
            players={}
            for view,bases in views:
                for player in bases:
                    key=player_key(player)
                    if key:
                        players[key]=player
            if players:
                with connection(ROOT/'player_history.sqlite3') as history:
                    ingest_records(history,players.values(),str(output),
                                   observed_at=timestamp())
                save_csv(folder/'players.csv',BASE_FIELDS,list(players.values()))
            save_status(folder,'initial_capture_saved',
                        initial_capture=str(output),
                        initial_map_views=len(views),
                        initial_unique_bases=len(players),
                        initial_decode_errors=failures)
            print(f'[capture] Initial world load: {len(views)} decoded map views, '
                  f'{len(players)} unique bases. Saved {output}',flush=True)
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:proc.wait(timeout=6)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)


def prepare_radar(cfg,args,folder):
    """Handle login/ads, leave city, zoom once, then use the fixed minimap ROI."""
    import cv2
    from data_miner.startup import (run_ai_startup,popup_visible,
                                   city_label_visible,promotion_content_visible)
    image=read_screen(cfg)
    save_screen(cfg,folder,'initial',image)
    save_status(folder,'startup_checks_no_ollama')
    print('Reusing login/ad handling, Ollama DISABLED for this pipeline.',flush=True)
    try:
        actions=run_ai_startup(cfg,max_actions=args.max_startup_actions,
                               allow_ai_fallback=False)
    except (RuntimeError,TimeoutError) as exc:
        # Preserve the actual ambiguous screen instead of only the login
        # screenshot. No speculative top-right click is allowed.
        try:
            save_screen(cfg,folder,'startup_stopped_screenshot',read_screen(cfg))
        except (OSError,RuntimeError) as capture_error:
            print(f'[pipeline] Could not save blocked screen: {capture_error}',
                  flush=True)
        raise
    save_status(folder,'city_ready',startup_actions=actions)
    image=read_screen(cfg)
    save_screen(cfg,folder,'city_after_popups',image)
    # A gold top-right X is part of the city UI and MUST NOT be used
    # as a reason to reject the verified startup handoff. Check for
    # actual promotional content instead of reusing the X detector.
    if popup_visible(image):
        raise RuntimeError('Login warning still visible; refusing Leave City')
    if not city_label_visible(image) and promotion_content_visible(image):
        save_screen(cfg,folder,'unexpected_offer_before_leave_city',image)
        raise RuntimeError('Promotional offer remains; refusing Leave City')
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
    with initial_world_capture(args,folder):
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

        # The radar/minimap is at a known fixed ROI on this BlueStacks setup.
        # Do not require a template, OCR, or any post-zoom radar check.
        # Exactly one verified zoom hold is sent; network responses validate
        # subsequent clicks. Keep a diagnostic screenshot for inspection.
        if args.zoom_method=='bluestacks':
            from bluestacks_zoom import zoom_out_ctrl_minus
            print(f'[pipeline] Zoom out once: Ctrl+- held {args.zoom_hold:.1f}s',flush=True)
            zoom_out_ctrl_minus(args.zoom_hold)
        elif args.zoom_method=='tap':
            point=args.zoom_tap or (cfg.get('ui',{}).get('world_map',{}) or {}).get('zoom_out_tap')
            if point is None:
                raise RuntimeError('Zoom tap not calibrated; pass --zoom-tap X Y')
            one_tap(cfg,after,point,'Zoom out once')
        elif args.zoom_method=='keyevent':
            from scanner import adb
            if args.zoom_keyevent is None or not 1<=args.zoom_keyevent<=300:
                raise ValueError('Set a verified --zoom-keyevent between 1 and 300')
            adb(cfg,'shell','input','keyevent',str(args.zoom_keyevent))
        else:
            raise ValueError('Unknown zoom method: '+str(args.zoom_method))
        time.sleep(args.zoom_delay)
        zoomed=read_screen(cfg)
        save_screen(cfg,folder,'after_zoom',zoomed)
        save_status(folder,'zoom_complete_no_radar_check',
                    zoom_hold=args.zoom_hold,zoom_method=args.zoom_method,
                    radar_roi=list(args.roi))
        print('[pipeline] Zoom complete. Using fixed minimap ROI; '
              'no radar image/template check.',flush=True)


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
        raise ValueError('BlueStacks zoom-only requires exactly one held Ctrl+- action; set --zoom-steps 1')
    print(f'[zoom] Exactly one Ctrl+- hold for {args.zoom_hold:.1f}s; no extra zoom actions.',flush=True)
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
            print('[zoom] Little visible change after this hold. '
                  'Check BlueStacks Game controls > Zoom mapping/Override. '
                  'No additional holds will be sent.',flush=True)
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
    if args.fast_snake:
        from fast_snake_scan import fast_scan
        state=SimpleNamespace(roi=list(args.roi),stages=args.stages,
            pattern=args.pattern,out=folder,
            history_db=ROOT/'player_history.sqlite3',
            interface=args.interface,dumpcap=args.dumpcap,
            adb=None,serial=None,max_clicks=args.max_clicks,
            fast_interval=args.fast_interval,fast_batch=args.fast_batch)
        save_status(folder,'fast_serpentine_scanning',
                    grid=args.stages[0],click_interval=args.fast_interval,
                    batch_size=args.fast_batch)
        fast_scan(state)
        return
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
    from full_map_scan import load_players
    route_path=folder/'route.json'
    planned=(len(json.loads(route_path.read_text(encoding='utf-8'))['points'])
             if route_path.is_file() else 0)
    latest={row['target_id']:row for row in entries}
    completed=sum(row.get('status') in ('OK','OVERLAP','EMPTY')
                  for row in latest.values())
    review=sum(row.get('status') not in ('OK','OVERLAP','EMPTY')
               for row in latest.values())
    count=len(load_players(folder/'players.csv'))
    remaining=max(0,planned-completed-review)
    print(f'[scan] {count:,} / {args.goal:,} unique bases | '
          f'{completed:,}/{planned:,} confirmed minimap positions | '
          f'{remaining:,} not attempted | {review:,} review',flush=True)
    save_status(folder,'network_scan_recorded',
                successful_clicks=completed,all_click_results=len(entries),
                unique_bases=count,goal_bases=args.goal,
                planned_positions=planned,confirmed_positions=completed,
                positions_to_review=review,positions_not_attempted=remaining,
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
                       help='Zoom via BlueStacks Ctrl+-, tapped control, or Android keycode')
        a.add_argument('--max-zoom-actions',type=int,default=1,
                       help='Legacy zoom limit; BlueStacks always performs one hold')
        a.add_argument('--zoom-delay',type=float,default=.6)
        a.add_argument('--zoom-hold',type=float,default=2.0,
                       help='Continuous BlueStacks Ctrl+- key hold, 2–5 seconds (default 2)')
        a.add_argument('--max-startup-actions',type=int,default=12)
        a.add_argument('--execute',action='store_true')
        a.add_argument('--map-only',action='store_true',
                       help='Stop after fixed Leave City tap; no zoom or network scan')
        a.add_argument('--zoom-only',action='store_true',
                       help='Assume world map is already open; test BlueStacks zoom out and save screenshots, no scan')
        a.add_argument('--zoom-steps',type=int,default=1,
                       help='Zoom holds in zoom-only probe (exactly 1 for BlueStacks)')
        a.add_argument('--radar-template',type=Path,
                       help='Local cropped radar UI reference PNG for OpenCV matching')
        a.add_argument('--radar-only',action='store_true',
                       help='Inspect an already open world map: read-only radar verification twice, no taps or zoom')
        a.add_argument('--radar-threshold',type=float,default=.86)
        a.add_argument('--prepare-only',action='store_true',
                       help='Stop after Leave City and the one zoom hold; do not network-scan')
        a.add_argument('--startup-only',action='store_true',
                       help='Reuse Player Activity login confirmation and ad closing only; skip map and scan')
        a.add_argument('--pattern',choices=('spread','spiral','snake','checkerboard'),default='snake')
        a.add_argument('--stages',type=str,default='15')
        a.add_argument('--max-clicks',type=int,default=0,
                       help='Limit network-scan clicks for pilot; 0 scans all')
        a.add_argument('--seconds',type=int,default=3)
        a.add_argument('--legacy-scan',dest='fast_snake',action='store_false',
                       help='Use older one-capture-per-click scanner instead of fast batched snake')
        a.add_argument('--fast-interval',type=float,default=.3,
                       help='Target time between minimap taps (0.2 to under 1 second); default 0.30')
        a.add_argument('--fast-batch',type=int,default=10,
                       help='Checkpoint print/save frequency (2 to 40); no capture pause')
        a.set_defaults(fast_snake=True)
        a.add_argument('--retries',type=int,default=2)
        a.add_argument('--goal',type=int,default=9700)
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
    if not 2.0<=args.zoom_hold<=5.0:
        p.error('--zoom-hold must be between 2.0 and 5.0 seconds')
    if args.zoom_steps!=1:
        p.error('--zoom-steps must be exactly 1 for this BlueStacks setup')
    if args.zoom_method=='bluestacks' and args.max_zoom_actions!=1:
        p.error('BlueStacks zoom requires exactly one hold; use --max-zoom-actions 1')
    if args.max_zoom_actions<1 or args.max_zoom_actions>30 or not .2<=args.zoom_delay<=4:
        p.error('Zoom limits invalid')
    if not .6<=args.radar_threshold<=.99:
        p.error('--radar-threshold must be between 0.6 and 0.99')
    if args.max_startup_actions<1 or args.max_startup_actions>30 or args.max_clicks<0:
        p.error('Startup/click limit invalid')
    if not 3<=args.seconds<=30 or not 1<=args.retries<=5:
        p.error('Capture interval/retries invalid')
    if args.fast_snake and (args.pattern!='snake' or len(args.stages)!=1):
        p.error('Fast serpentine requires --pattern snake and one --stages grid (e.g. 20)')
    if args.fast_snake and (not .2<=args.fast_interval<1 or not 2<=args.fast_batch<=40):
        p.error('Fast interval must be 0.2..<1 seconds and checkpoint size 2..40')
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
        print('Ollama-free: confirm, dismiss ads, Leave City, zoom once, then scan fixed minimap ROI.')
        print(f'Zoom uses one continuous Ctrl+- hold for {args.zoom_hold:.1f}s, not repeated key taps.')
        print('Start: confirm login -> dismiss promotions -> Leave City -> zoom to radar')
        print('Then: passive scan '+str(args.stages)+' '+args.pattern+
              ' ; player names stored in '+str(ROOT/'player_history.sqlite3'))
        return
    from pattern_benchmark import ensure_adb_device
    ensure_adb_device(SimpleNamespace(adb=cfg['adb_path'],serial=cfg['adb_serial']))
    try:
        if args.command=='inspect' and args.radar_only:
            if not args.radar_template:
                raise ValueError('Provide --radar-template PATH for read-only radar inspection')
            image=read_screen(cfg)
            save_screen(cfg,folder,'radar_inspect_first',image)
            first,score=radar_template_match(image,args.radar_template,
                                             args.roi,args.radar_threshold)
            print(f'[radar] first check {score:.3f} (threshold {args.radar_threshold:.3f})',flush=True)
            if not first:
                raise RuntimeError('Radar reference did not match the open world-map screenshot')
            time.sleep(.5)
            image2=read_screen(cfg)
            save_screen(cfg,folder,'radar_inspect_second',image2)
            second,score2=radar_template_match(image2,args.radar_template,
                                               args.roi,args.radar_threshold)
            print(f'[radar] second check {score2:.3f} (threshold {args.radar_threshold:.3f})',flush=True)
            if not second:
                raise RuntimeError('Radar reference did not match the second screenshot')
            save_status(folder,'radar_inspection_passed',scores=[round(score,3),round(score2,3)])
            print('RADAR INSPECTION PASSED: no clicks, zoom, or network scanning.',flush=True)
            return
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
            print('ZOOM COMPLETE. No network scanning requested.',flush=True)
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
