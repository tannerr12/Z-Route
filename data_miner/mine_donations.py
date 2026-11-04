"""Extract Alliance Ranking > Donate > This Week by screenshot and scroll."""
import csv
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from scanner import adb, screenshot
from data_miner.target_locator import ask_vision
from data_miner.select_donations import read_state

OUT = Path(__file__).resolve().parent / "output"
CSV_PATH = OUT / "donations.csv"
FIELDS = ["week_start", "rank", "username", "role", "points", "captured_at", "evidence"]


def extract_donations(cfg, image):
    result = ask_vision(cfg, image,
        "Read only completely visible rows of the scrollable Alliance Ranking "
        "Donate This Week leaderboard. Ignore the fixed/pinned player row "
        "at the bottom, even if it shows a rank. Ignore partly clipped rows. "
        "Return JSON object with rows array. Each row: rank integer, "
        "username exact text, role string R1/R2/R3/R4/R5 or null, "
        "points integer. Do not guess unreadable values.")
    rows = result.get("rows")
    if not isinstance(rows, list):
        raise ValueError("Invalid donation extraction response")
    valid = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        rank, username, role, points = (row.get(k) for k in ("rank", "username", "role", "points"))
        if (isinstance(rank, bool) or not isinstance(rank, int) or not 1 <= rank <= 100
                or not isinstance(username, str) or not username.strip()
                or isinstance(points, bool) or not isinstance(points, int) or points < 0
                or role not in (None, "R1", "R2", "R3", "R4", "R5")):
            continue
        valid.append({"rank": str(rank), "username": username.strip(),
                      "role": role or "", "points": str(points)})
    return valid


def write_donations(week_start, rows, evidence):
    OUT.mkdir(parents=True, exist_ok=True)
    records = {}
    if CSV_PATH.exists():
        with CSV_PATH.open(encoding="utf-8", newline="") as f:
            for record in csv.DictReader(f):
                records[(record["week_start"], record["rank"])] = record
    now = datetime.now(timezone.utc).isoformat()
    for row in rows:
        key = (week_start, row["rank"])
        record = {"week_start": week_start, **row, "captured_at": now, "evidence": str(evidence)}
        if key in records:
            old = records[key]
            if old["username"] != record["username"] or old["points"] != record["points"]:
                raise RuntimeError(f"Conflicting donation row {key}; inspect {evidence}")
        records[key] = record
    tmp = CSV_PATH.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(records.values())
    tmp.replace(CSV_PATH)


def scroll_donations(cfg, image):
    h, w = image.shape[:2]
    x = round(w * .53)
    adb(cfg, "shell", "input", "swipe",
        str(x), str(round(h * .73)), str(x), str(round(h * .34)), "450")
    time.sleep(.5)


def mine_donations(cfg, week_start, max_swipes=40):
    state = read_state(cfg, screenshot(cfg))
    if state.get("category") != "Donate" or state.get("period") != "This Week":
        raise RuntimeError("Expected Donate / This Week before mining")
    seen = set()
    previous = None
    stationary = 0
    for step in range(max_swipes + 1):
        image = screenshot(cfg)
        evidence = OUT / "screenshots" / week_start / "donations" / f"{step:03d}.png"
        evidence.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(evidence), image):
            raise RuntimeError("Failed to save donation screenshot")
        rows = extract_donations(cfg, image)
        write_donations(week_start, rows, evidence)
        seen.update(int(row["rank"]) for row in rows)
        if 100 in seen:
            return len(seen), "rank 100 reached"
        h, w = image.shape[:2]
        crop = cv2.resize(image[int(h*.18):int(h*.79), int(w*.02):int(w*.98)], (300, 300))
        if previous is not None:
            diff = float(np.mean(cv2.absdiff(previous, crop)))
            stationary = stationary + 1 if diff < 2.5 else 0
            if stationary >= 2:
                return len(seen), "bottom detected (no movement)"
        previous = crop
        if step < max_swipes:
            scroll_donations(cfg, image)
    raise RuntimeError("Donation swipe limit reached; inspect screenshots")
