"""Read-only Z-Route Alliance activity log scanner.

Run: python -m data_miner.player_activity --max-swipes 5 --verbose
Evidence is saved locally; CSV export is opt-in with --write-csv.
"""
import argparse
import csv
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from scanner import adb, load_config, screenshot, save_capture_png, ensure_game_connected
from data_miner.startup import run_ai_startup
from data_miner.open_alliance import open_alliance
from data_miner.target_locator import ask_vision, locate_text_button

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "player_activity"
EVIDENCE = ROOT / "data_miner" / "output" / "player_activity"
ATTACK_FIELDS = ["timestamp", "attacker", "attacker_guild", "attacker_server",
                 "attacked", "attacked_guild", "destination_server",
                 "destination_x", "destination_y", "outcome", "scanned_at"]
CHANGE_FIELDS = ["timestamp", "player", "guild", "event", "scanned_at"]
TIME_RE = re.compile(r"^20\d{2}[.-]\d{1,2}[.-]\d{1,2}[ T]\d{1,2}:\d{2}:\d{2}$")
GUILD_RE = re.compile(r"^\[([A-Za-z0-9_-]{1,12})\]$")
COORD_RE = re.compile(r"\[#(\d+)\s+X:(\d+)\s*,\s*Y:(\d+)\]", re.I)


def verified_screen(cfg, expected):
    image = screenshot(cfg)
    ensure_game_connected(cfg, image)
    result = ask_vision(cfg, image,
        f"Is this the Z-Route Alliance {expected} screen? Return JSON "
        "with expected_screen boolean and confidence number 0..1. "
        "If unsure return false. Do not guess.")
    confidence = result.get("confidence")
    if (result.get("expected_screen") is not True or
        isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or
        confidence < .8 or confidence > 1):
        raise RuntimeError(f"Expected Alliance {expected} screen not verified: {result}")
    return image


def click_label(cfg, label, context, region="any"):
    image = screenshot(cfg)
    ensure_game_connected(cfg, image)
    x, y = locate_text_button(cfg, image, label, context, region)
    adb(cfg, "shell", "input", "tap", str(x), str(y))
    time.sleep(.8)


def open_log(cfg):
    verified_screen(cfg, "home/menu")
    click_label(cfg, "Log button", "Alliance home/menu, lower navigation area", "bottom")
    verified_screen(cfg, "Log with War and Join/Leave tabs")


def select_tab(cfg, tab):
    verified_screen(cfg, "Log with War and Join/Leave tabs")
    click_label(cfg, tab + " tab", "Alliance Log, top tab bar", "top")
    verified_screen(cfg, "Log with " + tab + " tab selected")


def extract(cfg, image, tab):
    if tab == "War":
        prompt = (
            "Read only FULLY VISIBLE individual attack events in the scrolling "
            "War activity list. Each event may span several lines and has a date/time. "
            "Return JSON with events array. Each event object: timestamp (exact visible "
            "YYYY.MM.DD HH:MM:SS), attacker (username without guild tag), "
            "attacker_guild (tag without brackets or empty), attacker_server "
            "(number string or empty), attacked (victim username without guild tag), "
            "attacked_guild (tag without brackets or empty), destination_server "
            "(number string from the coordinates AFTER victim Base), destination_x, "
            "destination_y (integer or null), outcome (exact visible outcome or empty). "
            "Only use visible text; do not infer missing values. Exclude partial rows.")
    else:
        prompt = (
            "Read only FULLY VISIBLE Join/Leave events from the scrolling Alliance Log. "
            "Return JSON with events array. Each event object: timestamp (exact visible "
            "YYYY.MM.DD HH:MM:SS), player (exact username), guild (visible guild tag "
            "without brackets, or empty), event ('joined' or 'left'). "
            "Do not guess missing dates, names, or events; exclude partial rows.")
    result = ask_vision(cfg, image, prompt + " Ignore navigation, headers and overlays.")
    events = result.get("events")
    if not isinstance(events, list):
        raise RuntimeError(f"{tab}: Ollama did not return an events array")
    cleaned = []
    for event in events:
        if not isinstance(event, dict):
            continue
        stamp = event.get("timestamp")
        if not isinstance(stamp, str) or not TIME_RE.fullmatch(stamp.strip()):
            continue
        if tab == "War":
            attacker, victim = event.get("attacker"), event.get("attacked")
            guild = event.get("attacked_guild")
            server = str(event.get("destination_server") or "").lstrip("#")
            if not all(isinstance(v, str) and v.strip() for v in (attacker, victim, guild)):
                continue
            guild = guild.strip().strip("[]")
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,12}", guild):
                continue
            if victim.strip().casefold().startswith("commander2") or server != "125":
                continue
            try:
                x, y = int(event["destination_x"]), int(event["destination_y"])
            except (KeyError, ValueError, TypeError):
                continue
            if not (0 <= x <= 9999 and 0 <= y <= 9999):
                continue
            cleaned.append({
                "timestamp": stamp.strip(), "attacker": attacker.strip(),
                "attacker_guild": str(event.get("attacker_guild") or "").strip(" []"),
                "attacker_server": str(event.get("attacker_server") or "").lstrip("#"),
                "attacked": victim.strip(), "attacked_guild": guild,
                "destination_server": server, "destination_x": x, "destination_y": y,
                "outcome": str(event.get("outcome") or "").strip()})
        else:
            player = event.get("player")
            action = str(event.get("event") or "").strip().lower()
            if not isinstance(player, str) or not player.strip() or action not in ("joined", "left"):
                continue
            cleaned.append({"timestamp": stamp.strip(), "player": player.strip(),
                            "guild": str(event.get("guild") or "").strip(" []"),
                            "event": action})
    return cleaned


def event_key(tab, row):
    if tab == "War":
        return tuple(str(row.get(k, "")).casefold() for k in
                     ("timestamp", "attacker", "attacked", "destination_server",
                      "destination_x", "destination_y"))
    return tuple(str(row.get(k, "")).casefold() for k in
                 ("timestamp", "player", "event"))


def save_csv(tab, rows):
    DATA.mkdir(parents=True, exist_ok=True)
    path = DATA / ("attacks.csv" if tab == "War" else "guild_changes.csv")
    fields = ATTACK_FIELDS if tab == "War" else CHANGE_FIELDS
    existing = []
    if path.exists():
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames and any(field not in reader.fieldnames for field in fields):
                raise RuntimeError(f"CSV schema mismatch: {path}")
            existing = list(reader)
    keys = {event_key(tab, row) for row in existing}
    for row in rows:
        key = event_key(tab, row)
        if key not in keys:
            existing.append({field: row.get(field, "") for field in fields})
            keys.add(key)
    temp = path.with_suffix(".tmp")
    with temp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(existing)
    temp.replace(path)
    return len(keys)


def list_crop(image):
    h, w = image.shape[:2]
    return cv2.resize(image[int(h*.20):int(h*.83), int(w*.05):int(w*.95)],
                      (280, 280))


def scan_tab(cfg, tab, max_swipes, folder, verbose):
    rows = {}
    previous = None
    stationary = 0
    reason = "swipe limit reached"
    for step in range(max_swipes + 1):
        image = screenshot(cfg)
        ensure_game_connected(cfg, image)
        evidence = folder / tab.lower().replace("/", "_") / f"{step:03d}.png"
        evidence.parent.mkdir(parents=True, exist_ok=True)
        save_capture_png(cfg, evidence, image)
        found = extract(cfg, image, tab)
        for row in found:
            rows.setdefault(event_key(tab, row), row)
        if verbose:
            print(f"{tab} capture {step}: {len(found)} validated events, "
                  f"{len(rows)} unique; evidence {evidence}", flush=True)
        crop = list_crop(image)
        if previous is not None:
            difference = float(np.mean(cv2.absdiff(previous, crop)))
            stationary = stationary + 1 if difference < 2.5 else 0
            if verbose:
                print(f"  list movement difference: {difference:.2f}", flush=True)
            if stationary >= 2:
                reason = "bottom detected"
                break
        previous = crop
        if step < max_swipes:
            h, w = image.shape[:2]
            x = int(w*.53)
            adb(cfg, "shell", "input", "swipe", str(x), str(int(h*.75)),
                str(x), str(int(h*.34)), "450")
            time.sleep(.7)
    return list(rows.values()), reason


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-swipes", type=int, default=5)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--write-csv", action="store_true",
                        help="Append deduplicated events to local CSVs; off by default")
    parser.add_argument("--skip-startup", action="store_true",
                        help="Use only when already on the Alliance home screen")
    args = parser.parse_args()
    if not 0 <= args.max_swipes <= 100:
        parser.error("--max-swipes must be between 0 and 100")
    cfg = load_config()
    folder = EVIDENCE / datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    folder.mkdir(parents=True, exist_ok=True)
    if not args.skip_startup:
        run_ai_startup(cfg)
        open_alliance(cfg)
    open_log(cfg)
    for tab in ("War", "Join/Leave"):
        select_tab(cfg, tab)
        rows, reason = scan_tab(cfg, tab, args.max_swipes, folder, args.verbose)
        print(f"{tab}: {len(rows)} unique validated events; {reason}", flush=True)
        if args.write_csv:
            stamp = datetime.now(timezone.utc).isoformat()
            for row in rows:
                row["scanned_at"] = stamp
            print(f"  CSV now has {save_csv(tab, rows)} unique events", flush=True)
    print(f"Evidence saved to {folder}", flush=True)
    if not args.write_csv:
        print("Read-only test: no CSVs changed. Add --write-csv after reviewing evidence.")


if __name__ == "__main__":
    main()
