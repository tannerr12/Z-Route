"""Mine My Alliance leaderboard for MON-SAT via screenshots, Ollama and ADB.

Run: python -m data_miner.mine_rankings
Writes data_miner/output/rankings.csv and screenshot evidence.
"""
import csv
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from scanner import adb, load_config, screenshot
from data_miner.filter_rankings import filter_monday_alliance, ranking_state, require_rankings
from data_miner.target_locator import ask_vision, locate_text_button
from data_miner.open_rankings import open_rankings
from data_miner.open_vs import open_vs
from data_miner.startup import run_ai_startup
from data_miner.weekly_rankings import select_this_week
from data_miner.back_to_competition import back_to_competition

DAYS = ("MON", "TUE", "WED", "THUR", "FRI", "SAT")
OUT = Path(__file__).resolve().parent / "output"
CSV_PATH = OUT / "rankings.csv"
HEADERS = ["week_start", "day", "rank", "username", "alliance", "points", "captured_at", "evidence"]
MAX_RANK = 100


def extract_rows(cfg, image):
    h, w = image.shape[:2]
    result = ask_vision(cfg, image,
        "Read only FULLY VISIBLE leaderboard rows in the SCROLLABLE LIST on this "
        "Z-Route RANK screen. Ignore the sticky/pinned own-player row near the "
        "bottom, the top navigation, and any partially obscured rows. "
        "For each row return rank integer, username exact visible text, "
        "alliance exact visible tag or null, points integer. Do not guess. "
        "Return JSON object with rows array, each containing rank, username, "
        "alliance, points. Use [] if no readable rows.")
    rows = result.get("rows")
    if not isinstance(rows, list):
        raise ValueError("Ollama did not return rows array")
    clean = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        rank, name, alliance, points = (row.get(k) for k in ("rank", "username", "alliance", "points"))
        if (isinstance(rank, bool) or not isinstance(rank, int) or
            not 1 <= rank <= MAX_RANK or not isinstance(name, str) or
            not name.strip() or isinstance(points, bool) or
            not isinstance(points, int) or points < 0):
            continue
        if alliance is not None and not isinstance(alliance, str):
            continue
        clean.append({"rank": rank, "username": name.strip(),
                      "alliance": alliance.strip() if alliance else "", "points": points})
    return clean


def save_rows(week_start, day, rows, evidence):
    OUT.mkdir(parents=True, exist_ok=True)
    existing = {}
    if CSV_PATH.exists():
        with CSV_PATH.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                existing[(row["week_start"], row["day"], row["rank"])] = row
    timestamp = datetime.now(timezone.utc).isoformat()
    for row in rows:
        key = (week_start, day, str(row["rank"]))
        record = {"week_start": week_start, "day": day,
                  **row, "captured_at": timestamp, "evidence": str(evidence)}
        record["rank"] = str(record["rank"])
        record["points"] = str(record["points"])
        previous = existing.get(key)
        if previous and (previous["username"] != record["username"] or previous["points"] != record["points"]):
            raise RuntimeError(f"Conflicting extraction for {key}; review {evidence}")
        existing[key] = record
    temp = CSV_PATH.with_suffix(".tmp")
    with temp.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(existing.values())
    temp.replace(CSV_PATH)


def list_crop(image):
    h, w = image.shape[:2]
    # Only the scrollable leaderboard, excluding the pinned self row.
    return image[int(h * .18):int(h * .79), int(w * .02):int(w * .98)]


def scroll_up(cfg, image):
    h, w = image.shape[:2]
    x = int(w * .53)
    adb(cfg, "shell", "input", "swipe",
        str(x), str(int(h * .71)), str(x), str(int(h * .33)), "450")
    time.sleep(.5)


def select_day(cfg, day):
    image = screenshot(cfg)
    state = ranking_state(cfg, image)
    require_rankings(state)
    if state.get("my_alliance_checked") is not True:
        raise RuntimeError("My Alliance filter is not enabled")
    if state.get("selected_day") != day:
        x, y = locate_text_button(cfg, image, f"{day} weekday tab",
                                  "RANK screen, Today weekday navigation", "top")
        adb(cfg, "shell", "input", "tap", str(x), str(y))
        time.sleep(.5)
        state = ranking_state(cfg, screenshot(cfg))
        require_rankings(state)
        if state.get("selected_day") != day or state.get("my_alliance_checked") is not True:
            raise RuntimeError(f"Could not verify {day} and My Alliance filter")


def mine_day(cfg, week_start, day, max_swipes=40):
    if day != "WEEKLY":
        select_day(cfg, day)
    seen_ranks = set()
    previous = None
    stationary = 0
    for step in range(max_swipes + 1):
        image = screenshot(cfg)
        evidence = OUT / "screenshots" / week_start / day / f"{step:03d}.png"
        evidence.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(evidence), image)
        rows = extract_rows(cfg, image)
        save_rows(week_start, day, rows, evidence)
        seen_ranks.update(r["rank"] for r in rows)
        if MAX_RANK in seen_ranks:
            return len(seen_ranks), "rank 100 reached"
        crop = cv2.resize(list_crop(image), (300, 300))
        if previous is not None:
            diff = float(np.mean(cv2.absdiff(previous, crop)))
            if diff < 2.5:
                stationary += 1
            else:
                stationary = 0
            if stationary >= 2:
                return len(seen_ranks), "bottom detected (no movement)"
        previous = crop
        if step < max_swipes:
            scroll_up(cfg, image)
    raise RuntimeError(f"{day}: swipe safety limit reached; review screenshots before continuing")


def mine_week(cfg, week_start):
    # Caller supplies ISO date for Monday of the desired competition week.
    monday = datetime.strptime(week_start, "%Y-%m-%d")
    if monday.weekday() != 0:
        raise ValueError("week_start must be a Monday YYYY-MM-DD")
    run_ai_startup(cfg)
    open_vs(cfg)
    open_rankings(cfg)
    filter_monday_alliance(cfg)
    for day in DAYS:
        count, reason = mine_day(cfg, week_start, day)
        print(f"{day}: {count} unique ranks; {reason}")
    print("Weekly tab selected:", select_this_week(cfg))
    count, reason = mine_day(cfg, week_start, "WEEKLY")
    print(f"WEEKLY: {count} unique ranks; {reason}")
    print("Returned to Alliance Competition:", back_to_competition(cfg))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--week-start", required=True, help="Monday YYYY-MM-DD")
    args = parser.parse_args()
    mine_week(load_config(), args.week_start)
