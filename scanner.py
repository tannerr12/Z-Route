"""Z Route BlueStacks scanner: initial calibration and database prototype."""
import argparse
import base64
import urllib.request
import csv
import queue
import threading
import traceback
import faulthandler
import os
import ctypes
from difflib import SequenceMatcher
import json
import re
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
import pytesseract

ROOT = Path(__file__).resolve().parent
DB = ROOT / "players.sqlite3"
COORDS = re.compile(r"s\s*[:=]\s*(\d+)\s*x\s*[:=]\s*(\d+)\s*y\s*[:=]\s*(\d+)", re.I)


def setup_db():
    db = sqlite3.connect(DB)
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS guilds(
      id INTEGER PRIMARY KEY, server INTEGER NOT NULL,
      tag TEXT NOT NULL COLLATE NOCASE, name TEXT,
      UNIQUE(server,tag));
    CREATE TABLE IF NOT EXISTS players(
      id INTEGER PRIMARY KEY, server INTEGER NOT NULL,
      username TEXT NOT NULL COLLATE NOCASE,
      guild_id INTEGER REFERENCES guilds(id),
      x INTEGER, y INTEGER, last_seen TEXT,
      UNIQUE(server,username));
    CREATE TABLE IF NOT EXISTS observations(
      id INTEGER PRIMARY KEY, player_id INTEGER REFERENCES players(id),
      observed_at TEXT NOT NULL, x INTEGER, y INTEGER,
      guild_id INTEGER REFERENCES guilds(id), evidence TEXT);
    CREATE TABLE IF NOT EXISTS guild_memberships(
      id INTEGER PRIMARY KEY, player_id INTEGER REFERENCES players(id),
      guild_id INTEGER REFERENCES guilds(id),
      first_seen TEXT NOT NULL, last_seen TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS scan_progress(
      tile_row INTEGER, tile_col INTEGER, completed_at TEXT,
      PRIMARY KEY(tile_row,tile_col));
    """)
    db.commit()
    return db


def load_config():
    path = ROOT / "config.json"
    if not path.exists():
        raise SystemExit("Copy config.example.json to config.json first.")
    cfg = json.loads(path.read_text(encoding="utf-8"))
    if cfg.get("tesseract_path"):
        pytesseract.pytesseract.tesseract_cmd = cfg["tesseract_path"]
    return cfg


def adb(cfg, *args):
    exe = cfg.get("adb_path") or "adb"
    serial = cfg.get("adb_serial") or "127.0.0.1:5555"
    started = time.perf_counter()
    result = subprocess.run([exe, "-s", serial, *args],
                            check=True, capture_output=True, timeout=30).stdout
    metrics = cfg.get("_capture_metrics")
    if metrics is not None:
        category = "screenshot_adb" if args[:3] == ("exec-out", "screencap", "-p") else "swipe_adb" if args[:3] == ("shell", "input", "swipe") else "other_adb"
        metrics.setdefault(category, []).append(time.perf_counter() - started)
    return result


def screenshot(cfg):
    if cfg.get("_raw_capture_enabled"):
        import struct
        raw = adb(cfg, "exec-out", "screencap")
        if len(raw) < 12:
            raise RuntimeError("Incomplete RAW screenshot")
        width, height, fmt = struct.unpack_from("<III", raw)
        channels = {1: 4, 2: 4, 3: 3}.get(fmt)
        if not (0 < width <= 8192 and 0 < height <= 8192) or channels is None:
            raise RuntimeError(f"Unsupported RAW framebuffer: {width}x{height}, format {fmt}")
        offset = len(raw) - width * height * channels
        if offset not in (12, 16):
            raise RuntimeError(f"Invalid RAW framebuffer header: {offset}")
        pixels = np.frombuffer(raw, np.uint8, count=width*height*channels, offset=offset)
        pixels = pixels.reshape(height, width, channels)
        image = cv2.cvtColor(pixels, cv2.COLOR_RGBA2BGR if channels == 4 else cv2.COLOR_RGB2BGR)
        cfg["_last_capture_png"] = None
        cfg["_last_capture_image_id"] = id(image)
        return image
    raw = adb(cfg, "exec-out", "screencap", "-p")
    started = time.perf_counter()
    image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    metrics = cfg.get("_capture_metrics")
    if metrics is not None:
        metrics.setdefault("png_decode", []).append(time.perf_counter() - started)
    if image is None:
        raise RuntimeError("Unable to decode screenshot")
    # Capture thread alone calls screenshot(); preserve original encoded bytes
    # for zero-reencode disk writes. The AI worker only reads saved files.
    cfg["_last_capture_png"] = raw
    cfg["_last_capture_image_id"] = id(image)
    return image


def save_capture_png(cfg, path, image):
    started = time.perf_counter()
    if cfg.get("_last_capture_image_id") == id(image) and cfg.get("_last_capture_png") is not None:
        path.write_bytes(cfg["_last_capture_png"])
    elif not cv2.imwrite(str(path), image):
        raise RuntimeError(f"Failed to save screenshot: {path}")
    metrics = cfg.get("_capture_metrics")
    if metrics is not None:
        metrics.setdefault("png_save", []).append(time.perf_counter() - started)


def scaled_swipe(start, end, scale, low, high):
    center = (start + end) / 2
    return (max(low, min(high, int(round(center + (start-center)*scale)))),
            max(low, min(high, int(round(center + (end-center)*scale)))))


def print_capture_metrics(cfg):
    metrics = cfg.get("_capture_metrics") or {}
    print("Capture timing summary (mean seconds per operation):")
    for name, values in metrics.items():
        if values:
            print(f"  {name}: {sum(values)/len(values):.3f}s across {len(values)} calls")


def connection_lost_dialog(image):
    """Recognize the specific Z-Route reconnect modal; never click it."""
    height, width = image.shape[:2]
    # Modal occupies the center of the game viewport. OCR only that region.
    crop = image[int(height * .24):int(height * .67),
                 int(width * .08):int(width * .94)]
    if crop.size == 0:
        return False
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=1.6, fy=1.6,
                      interpolation=cv2.INTER_LINEAR)
    text = pytesseract.image_to_string(gray, config="--psm 6").casefold()
    compact = " ".join(text.split())
    return ("failed to connect" in compact and
            ("server" in compact or "reconnect" in compact))


def ensure_game_connected(cfg, image, on_progress=None):
    if not connection_lost_dialog(image):
        return
    if on_progress:
        on_progress(None, "connection_lost")
    folder = scan_diagnostic_folder(cfg)
    stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
    path = folder / f"connection_lost_{stamp}.png"
    cv2.imwrite(str(path), image)
    raise RuntimeError(f"Z-Route connection lost; checkpoint preserved. "
                       f"Do not click Confirm automatically. Screenshot: {path}")


def recognize(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=2, fy=2)
    return pytesseract.image_to_string(gray, config="--psm 11")


DEFAULT_UI_MASKS = [
    [0.00, 0.56, 0.15, 0.88],  # left-side controls
    [0.70, 0.09, 1.00, 0.53],  # variable event icons, conservative envelope
    [0.75, 0.66, 1.00, 0.94],  # right-side alliance, bag and city controls
]


def ui_mask_rectangles(image, cfg):
    """Return normalized rectangles mapped to screenshot pixel coordinates."""
    height, width = image.shape[:2]
    raw = cfg.get("ocr", {}).get("ui_masks", DEFAULT_UI_MASKS)
    rectangles = []
    for coords in raw:
        if len(coords) != 4 or not all(isinstance(v, (int, float)) for v in coords):
            raise ValueError("Each OCR UI mask must contain four numeric ratios")
        x1, y1, x2, y2 = coords
        if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
            raise ValueError(f"Invalid OCR mask: {coords}")
        rectangles.append((int(x1 * width), int(y1 * height),
                           int(x2 * width), int(y2 * height)))
    return rectangles


def safe_scan_bounds(image, cfg):
    """Shared vertical safe area for OCR, grouping and diagnostics."""
    height = image.shape[0]
    ocr = cfg.get("ocr", {})
    top = min(150, height - 1)  # Read-only detection: no base-click clearance needed.
    bottom = int(height * (1 - float(ocr.get("bottom_exclusion_ratio", 0.09))))
    if top >= bottom:
        raise ValueError("OCR safe area is empty: check exclusion ratios")
    return top, bottom


def within_safe_area(box, top, bottom, masks, level_clearance=48):
    """Require the nameplate and potential level badge to fit in usable space."""
    x1, y1, x2, y2 = box
    if y1 < top or y2 + level_clearance > bottom:
        return False
    return not any(x1 < b and x2 > a and y1 < d and y2 + level_clearance > c
                   for a, c, b, d in masks)


def nameplate_candidates(image, bottom_exclusion_ratio=0.09, top_exclusion_ratio=0.08,
                         ui_rectangles=None):
    """Find text-like regions without depending on decorative nameplate borders.

    Returns candidate crops for OCR and manual review. This is a heuristic,
    not a trained building detector; click locations are not inferred here.
    """
    cutoff = int(image.shape[0] * (1 - bottom_exclusion_ratio))
    top = int(image.shape[0] * top_exclusion_ratio)
    gray = cv2.cvtColor(image[top:cutoff], cv2.COLOR_BGR2GRAY)
    for x1, y1, x2, y2 in (ui_rectangles or []):
        gray[max(0, y1-top):min(cutoff-top, y2), x1:x2] = 127
    enlarged = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    variants = [
        cv2.equalizeHist(enlarged),
        cv2.adaptiveThreshold(enlarged, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                              cv2.THRESH_BINARY, 31, 9),
    ]
    results = []
    for variant in variants:
        # Text detection via OCR boxes; decorative frames are not required.
        data = pytesseract.image_to_data(
            variant, config="--psm 11",
            output_type=pytesseract.Output.DICT)
        for i, token in enumerate(data["text"]):
            token = token.strip()
            if not token or len(token) < 3:
                continue
            try:
                confidence = float(data["conf"][i])
            except (ValueError, TypeError):
                continue
            if confidence < 25:
                continue
            x, y = data["left"][i] // 2, top + data["top"][i] // 2
            w, h = max(1, data["width"][i] // 2), max(1, data["height"][i] // 2)
            if any(x < x2 and x + w > x1 and y < y2 and y + h > y1
                   for x1, y1, x2, y2 in (ui_rectangles or [])):
                continue
            results.append((x, y, w, h, token, confidence))
    return results



GUILD_RE = re.compile(r"^\[([A-Za-z0-9]{2,8})\]$")
IGNORE_PHRASES = ("item expiring", "merit special", "upgrade highway",
                  "value pack", "return to city")


def grouped_player_candidates(tokens):
    """Conservative guild-anchored grouping, with spatial deduplication."""
    unique = []
    for t in sorted(tokens, key=lambda v: -v[5]):
        if any(abs(t[0]-u[0]) < 12 and abs(t[1]-u[1]) < 10
               and abs(t[2]-u[2]) < 15 for u in unique):
            continue
        unique.append(t)
    groups = []
    for x, y, w, h, word, confidence in unique:
        match = GUILD_RE.fullmatch(word.strip())
        if not match:
            continue
        words = sorted((t for t in unique
                        if t[0] >= x+w-4 and t[0] < x+w+145
                        and abs((t[1]+t[3]/2)-(y+h/2)) < 13),
                       key=lambda t: t[0])
        selected = []
        end = x+w
        for t in words:
            if t[0]-end > 18:
                break
            selected.append(t)
            end = t[0]+t[2]
        name = "".join(t[4] for t in selected).strip(" []|")
        if len(name) < 2 or len(name) > 32:
            continue
        if any(p in name.lower() for p in IGNORE_PHRASES):
            continue
        box = (x, min([y]+[t[1] for t in selected]),
               max(t[0]+t[2] for t in selected),
               max([y+h]+[t[1]+t[3] for t in selected]))
        if any(g["guild"] == match.group(1) and
               abs(g["box"][0]-x) < 20 and abs(g["box"][1]-y) < 16
               for g in groups):
            continue
        groups.append({"guild": match.group(1), "username": name,
                       "box": box, "confidence": round(confidence, 1)})
    return groups



def line_player_candidates(image, tokens, cfg):
    """Second-pass single-line OCR; guildless results are provisional."""
    height, width = image.shape[:2]
    masks = ui_mask_rectangles(image, cfg)
    top, bottom = safe_scan_bounds(image, cfg)
    bottom = int(height * (1-cfg.get("ocr", {}).get("bottom_exclusion_ratio", 0.09)))
    # Build horizontal word clusters, including untagged text.
    rows = []
    for t in sorted(tokens, key=lambda t: (t[1]+t[3]/2, t[0])):
        cy = t[1]+t[3]/2
        row = next((row for row in rows if abs(row["cy"]-cy) < 9), None)
        if row is None:
            row = {"cy": cy, "tokens": []}
            rows.append(row)
        row["tokens"].append(t)
    results = []
    for row in rows:
        ordered = sorted(row["tokens"], key=lambda t: t[0])
        clusters = []
        for t in ordered:
            if not clusters or t[0] - max(v[0]+v[2] for v in clusters[-1]) > 24:
                clusters.append([])
            clusters[-1].append(t)
        for cluster in clusters:
            x1 = max(0, min(t[0] for t in cluster)-5)
            y1 = max(top, min(t[1] for t in cluster)-5)
            x2 = min(width, max(t[0]+t[2] for t in cluster)+5)
            y2 = min(bottom, max(t[1]+t[3] for t in cluster)+5)
            if x2-x1 < 22 or y2-y1 < 8 or y2-y1 > 35:
                continue
            if any(x1 < b and x2 > a and y1 < d and y2 > c
                   for a,c,b,d in masks):
                continue
            crop = image[y1:y2, x1:x2]
            enlarged = cv2.resize(crop, None, fx=3, fy=3,
                                   interpolation=cv2.INTER_CUBIC)
            gray = cv2.cvtColor(enlarged, cv2.COLOR_BGR2GRAY)
            raw = pytesseract.image_to_string(gray, config="--psm 7").strip()
            raw = " ".join(raw.split())
            if not raw or len(raw) > 40:
                continue
            guild_match = re.match(r"^\[([A-Za-z0-9]{2,8})\]\s*(.+)$", raw)
            guild = guild_match.group(1) if guild_match else None
            name = (guild_match.group(2) if guild_match else raw).strip(" |[]")
            if not (2 <= len(name) <= 30) or not re.search("[A-Za-z]", name):
                continue
            if any(phrase in raw.casefold() for phrase in IGNORE_PHRASES):
                continue
            # Guildless candidates are deliberately low-trust pending popup verification.
            score = 0.65 if guild else 0.30
            results.append({"guild": guild, "username": name,
                            "box": (x1,y1,x2,y2), "confidence": score,
                            "verified": False})
    # Deduplicate by spatial proximity, prefer guilded candidates.
    output = []
    for item in sorted(results, key=lambda r: -r["confidence"]):
        if any(abs(item["box"][0]-old["box"][0]) < 22 and
               abs(item["box"][1]-old["box"][1]) < 14 for old in output):
            continue
        output.append(item)
    return sorted(output, key=lambda r: (r["box"][1],r["box"][0]))




def dark_strip_candidates(image, cfg):
    """Experimental dark nameplate detector; candidates are NOT verified bases.

    Finds horizontal low-luminance strips, then OCRs the whole strip. Does not
    assume a particular border colour or require a guild tag.
    """
    height, width = image.shape[:2]
    top, bottom = safe_scan_bounds(image, cfg)
    bottom = int(height * (1-cfg.get("ocr", {}).get("bottom_exclusion_ratio", .09)))
    masks = ui_mask_rectangles(image, cfg)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    # Local darkness handles terrain showing through translucent backgrounds.
    local = cv2.GaussianBlur(gray, (0, 0), 21)
    dark = ((gray.astype(np.int16) < local.astype(np.int16) - 12) &
            (gray < 115)).astype(np.uint8) * 255
    dark[:top] = 0
    dark[bottom:] = 0
    for x1, y1, x2, y2 in masks:
        dark[y1:y2, x1:x2] = 0
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (23, 5))
    joined = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(joined, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    proposals = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if not (48 <= w <= 240 and 12 <= h <= 42 and w / h >= 2.4):
            continue
        x1, y1 = max(0, x-5), max(top, y-3)
        x2, y2 = min(width, x+w+5), min(bottom, y+h+3)
        if any(x1 < b and x2 > a and y1 < d and y2 > c
               for a, c, b, d in masks):
            continue
        crop = image[y1:y2, x1:x2]
        enlarged = cv2.resize(crop, None, fx=3, fy=3,
                               interpolation=cv2.INTER_CUBIC)
        gray_crop = cv2.cvtColor(enlarged, cv2.COLOR_BGR2GRAY)
        variants = [cv2.equalizeHist(gray_crop),
                    cv2.adaptiveThreshold(gray_crop, 255,
                        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                        cv2.THRESH_BINARY, 31, 8)]
        readings = []
        for variant in variants:
            raw = " ".join(pytesseract.image_to_string(
                variant, config="--psm 7").split())
            if raw:
                readings.append(raw)
        if not readings:
            continue
        # Require two independent image variants to agree on the full text.
        parsed = []
        for raw in readings:
            match = re.match(r"^\[([A-Za-z0-9]{2,8})\]\s*(.+)$", raw)
            guild = match.group(1) if match else None
            username = (match.group(2) if match else raw).strip(" |[]")
            if not (3 <= len(username) <= 30) or not re.search(r"[A-Za-z]", username):
                continue
            if any(phrase in raw.casefold() for phrase in IGNORE_PHRASES):
                continue
            parsed.append((guild, username))
        if len(parsed) < 2 or parsed[0] != parsed[1]:
            continue
        guild, username = parsed[0]
        proposals.append({"guild": guild, "username": username,
                          "box": (x1, y1, x2, y2),
                          "confidence": 85.0, "source": "dark-strip",
                          "verified": False, "readings": readings})
    return proposals



def read_base_level(image, box):
    """Locate the dark oval badge and OCR its digits; return None if uncertain."""
    height, width = image.shape[:2]
    x1, y1, x2, y2 = box
    center = (x1 + x2) // 2
    # Search a wider region to allow for variable nameplate decoration/height.
    left, right = max(0, center - 42), min(width, center + 42)
    top, bottom = max(0, y2 + 2), min(height, y2 + 48)
    if right <= left or bottom <= top:
        return None
    region = image[top:bottom, left:right]
    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    # Badge should be a compact, relatively dark shape under the nameplate.
    binary = cv2.threshold(gray, 95, 255, cv2.THRESH_BINARY_INV)[1]
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    badges = []
    for contour in contours:
        bx, by, bw, bh = cv2.boundingRect(contour)
        if 25 <= bw <= 75 and 13 <= bh <= 35 and 1.2 <= bw / bh <= 4.0:
            if abs(left + bx + bw / 2 - center) <= 22:
                badges.append((bx, by, bw, bh))
    # Fall back to a centered crop when the translucent badge has weak edges.
    if not badges:
        badges = [(max(0, center-left-27), 0, min(54, right-left), min(35, bottom-top))]
    votes = []
    for bx, by, bw, bh in badges:
        crop = gray[by:by+bh, bx:bx+bw]
        if crop.size == 0:
            continue
        scaled = cv2.resize(crop, None, fx=5, fy=5,
                            interpolation=cv2.INTER_CUBIC)
        variants = [scaled, cv2.equalizeHist(scaled),
                    cv2.threshold(scaled, 0, 255,
                                  cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]]
        for variant in variants:
            for psm in (7, 8):
                value = pytesseract.image_to_string(
                    variant, config=f"--psm {psm} -c tessedit_char_whitelist=0123456789").strip()
                if re.fullmatch(r"\d{1,2}", value) and 1 <= int(value) <= 40:
                    votes.append(int(value))
    if not votes:
        return None
    counts = {value: votes.count(value) for value in set(votes)}
    best = max(counts, key=counts.get)
    # A single ambiguous digit (e.g. 5 instead of 25) is not sufficient evidence.
    if counts[best] < 2 or (best < 10 and len(votes) < 3):
        return None
    return best


def middle_scan_rectangle(image, cfg):
    """Conservative central scan region, normalized to screen resolution."""
    height, width = image.shape[:2]
    ratios = cfg.get("ocr", {}).get("middle_scan_region",
                                    [0.13, 0.16, 0.70, 0.82])
    if len(ratios) != 4 or not (0 <= ratios[0] < ratios[2] <= 1 and
                               0 <= ratios[1] < ratios[3] <= 1):
        raise ValueError("Invalid ocr.middle_scan_region")
    return (int(width * ratios[0]), min(150, int(height * ratios[1])),
            int(width * ratios[2]), int(height * ratios[3]))


def anchored_nameplate_ocr(image, tokens, cfg):
    """OCR full nameplate rows, seeded by any text token, not only guild tags.

    Multiple OCR passes help recover names whose guild tags were segmented.
    Candidates still require a level badge in combined_player_candidates.
    """
    height, width = image.shape[:2]
    rx1, ry1, rx2, ry2 = middle_scan_rectangle(image, cfg)
    results = []
    seeds = []
    for x, y, w, h, word, confidence in tokens:
        if confidence < 35 or not (rx1 + 8 <= x < rx2 - 40 and
                                   ry1 + 8 <= y < ry2 - 55):
            continue
        if h > 32 or w > 210:
            continue
        if any(abs(x - sx) < 35 and abs(y - sy) < 16 for sx, sy in seeds):
            continue
        seeds.append((x, y))
        # The text may start at the guild tag or at the username.
        # Expand to both sides, but never beyond the safe central rectangle.
        left = max(rx1 + 6, x - 65)
        right = min(rx2 - 6, x + max(190, w + 105))
        top = max(ry1 + 6, y - 7)
        bottom = min(ry2 - 48, y + h + 8)
        if bottom <= top or right <= left:
            continue
        crop = image[top:bottom, left:right]
        enlarged = cv2.resize(crop, None, fx=3, fy=3,
                               interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(enlarged, cv2.COLOR_BGR2GRAY)
        variants = [gray, cv2.equalizeHist(gray),
                    cv2.threshold(gray, 0, 255,
                                  cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]]
        readings = []
        for variant in variants:
            raw = " ".join(pytesseract.image_to_string(
                variant, config="--psm 7").split())
            match = re.search(r"\\[([A-Za-z0-9]{2,8})\\]\\s*(.{3,30})", raw)
            if match:
                guild, name = match.group(1), match.group(2).strip(" |[]")
            else:
                guild, name = None, raw.strip(" |[]")
            if not (3 <= len(name) <= 30 and re.search(r"[A-Za-z]", name)):
                continue
            if any(p in name.casefold() for p in IGNORE_PHRASES):
                continue
            readings.append((guild, name))
        if len(readings) < 2:
            continue
        # Require agreement across preprocessing variants; do not invent names.
        from collections import Counter
        (guild, name), count = Counter(readings).most_common(1)[0]
        if count < 2:
            continue
        results.append({"guild": guild, "username": name,
                        "box": (left, top, right, bottom),
                        "confidence": 82.0 if guild else 76.0,
                        "source": "full-row-ocr", "verified": False})
    return results


def combined_player_candidates(image, tokens, cfg):
    """Only complete, high-confidence central nameplates with level evidence.

    Read-only diagnostics. These candidates must still be verified before
    any database write or automated base interaction.
    """
    region = middle_scan_rectangle(image, cfg)
    rx1, ry1, rx2, ry2 = region
    masks = []  # The middle region already excludes fixed UI panels.
    anchored = grouped_player_candidates(tokens)
    full_rows = anchored_nameplate_ocr(image, tokens, cfg)
    lines = line_player_candidates(image, tokens, cfg)
    dark_strips = dark_strip_candidates(image, cfg)
    proposals = (full_rows +
                 [dict(item, source="guild-anchor") for item in anchored] +
                 [dict(item, source="line-ocr") for item in lines] +
                 dark_strips)
    accepted = []
    for item in proposals:
        x1, y1, x2, y2 = item["box"]
        # Leave room for the level badge and avoid clipped nameplates.
        if not (rx1 + 5 <= x1 < x2 <= rx2 - 5 and
                ry1 + 5 <= y1 < y2 + 42 <= ry2 - 5):
            continue
        if any(x1 < b and x2 > a and y1 < d and y2 + 42 > c
               for a, c, b, d in masks):
            continue
        name = item["username"].strip()
        if not (3 <= len(name) <= 30 and re.search(r"[A-Za-z]", name)):
            continue
        if any(phrase in name.casefold() for phrase in IGNORE_PHRASES):
            continue
        # Reject OCR fragments and decorative punctuation; allow Unicode names.
        if name.startswith(("[", "]", "|")) or name.endswith(("[", "]", "|")):
            continue
        confidence = float(item["confidence"])
        if item["source"] in ("guild-anchor", "full-row-ocr"):
            if confidence < 75:
                continue
        elif item["source"] == "line-ocr":
            if not item.get("guild") or confidence < 0.60:
                continue
        elif item["source"] == "dark-strip":
            # Independent OCR agreement plus a level badge is required.
            if confidence < 80:
                continue
        else:
            continue
        level = read_base_level(image, item["box"])
        if level is None:
            continue
        candidate = {**item, "level": level, "level_supported": True,
                     "verified": False}
        if any(abs((x1+x2)/2 - (v["box"][0]+v["box"][2])/2) < 45
               and abs((y1+y2)/2 - (v["box"][1]+v["box"][3])/2) < 20
               for v in accepted):
            continue
        accepted.append(candidate)
    return sorted(accepted, key=lambda g: (g["box"][1], g["box"][0]))


def verify_sparse_vertical_shift(before, after, direction):
    """Conservative terrain-edge alignment; does not establish boundaries."""
    h, w = before.shape
    if after.shape != before.shape or h < 300 or w < 150:
        return None
    sign = -1 if direction == "up" else 1
    scores = []
    for shift in range(30, min(950, h - 110) + 1, 5):
        overlap = h - shift
        if sign < 0:
            a, b = before[shift:, :], after[:overlap, :]
        else:
            a, b = before[:overlap, :], after[shift:, :]
        ea, eb = cv2.Canny(a, 60, 150), cv2.Canny(b, 60, 150)
        na, nb = np.count_nonzero(ea), np.count_nonzero(eb)
        if na < 200 or nb < 200:
            continue
        agreement = 2 * np.count_nonzero((ea > 0) & (eb > 0)) / (na + nb)
        scores.append((agreement, shift))
    if not scores:
        return None
    best, displacement = max(scores)
    alternative = max((v for v, d in scores if abs(d - displacement) >= 30), default=0)
    if best < .55 or best - alternative < .12:
        print(f"Sparse terrain alignment inconclusive: best={best:.2f}, "
              f"alternative={alternative:.2f}.")
        return None
    print(f"Sparse terrain movement verified: dy={sign * displacement}px "
          f"(edge agreement={best:.2f}, alternative={alternative:.2f}).")
    return float(sign * displacement)


def scan_diagnostic_folder(cfg):
    """Session-specific diagnostics during a serpentine run; legacy folder otherwise."""
    folder = Path(cfg.get("_scan_session_folder") or ROOT / "screenshots")
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def scan_column(cfg, max_swipes=5, direction="up", verify_after=0, on_player=None, start_step=0, on_progress=None, swipe_ms=100, settle=0.2, capture_queue=None, vertical_scale=1.0):
    """Bounded read-only vertical scan, stopping on unverified movement."""
    if direction not in ("up", "down"):
        raise ValueError("direction must be up or down")
    if not 100 <= swipe_ms <= 1000 or not 0 <= settle <= 3:
        raise ValueError("Invalid swipe timing")
    folder = scan_diagnostic_folder(cfg)
    stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
    observations = []
    seen = set()
    previous_players = []
    previous = None
    if not 1 <= max_swipes <= 500:
        raise ValueError("max_swipes must be between 1 and 500")
    stop_reason = "swipe limit reached"
    completed_views = 0
    failed_views = 0
    consecutive_failures = 0
    def capture_with_retry(step):
        # Read-only retries: never swipe, tap, reconnect, or reset BlueStacks.
        # A screenshot timeout does not establish whether a previous swipe
        # completed, so preserve the current checkpoint and map position.
        delays = (2, 4, 8, 16)
        log_path = folder / "adb_screenshot_errors.log"
        for attempt in range(1, 6):
            started = time.monotonic()
            try:
                image = screenshot(cfg)
                if attempt > 1:
                    message = (f"[ADB RECOVERED] view={step} attempt={attempt}/5 "
                               f"elapsed={time.monotonic()-started:.1f}s")
                    print(message, flush=True)
                    with log_path.open("a", encoding="utf-8") as log:
                        log.write(f"{datetime.now(timezone.utc).isoformat()} {message}\n")
                return image
            except (subprocess.TimeoutExpired, subprocess.CalledProcessError,
                    OSError) as exc:
                elapsed = time.monotonic() - started
                message = (f"[ADB SCREENSHOT ERROR] view={step} attempt={attempt}/5 "
                           f"elapsed={elapsed:.1f}s type={type(exc).__name__} "
                           f"details={exc}")
                print(message, flush=True)
                with log_path.open("a", encoding="utf-8") as log:
                    log.write(f"{datetime.now(timezone.utc).isoformat()} {message}\n")
                if attempt == 5:
                    raise RuntimeError(
                        f"ADB screenshot failed after 5 attempts at view {step}; "
                        f"no additional swipe performed. Check {log_path}. "
                        "Checkpoint and captured screenshots preserved.") from exc
                delay = delays[attempt-1]
                print(f"[ADB RETRY] Waiting {delay}s before retrying screenshot at same position", flush=True)
                time.sleep(delay)

    for step in range(start_step, max_swipes + 1):
        if on_progress:
            on_progress(step, "view")
        dx = dy = None
        image = capture_with_retry(step)
        ensure_game_connected(cfg, image, on_progress)
        if previous is not None and step > verify_after:
            movement_verified = False
            for movement_attempt in range(1, 4):
                if movement_attempt > 1:
                    print(f"Retrying movement verification ({movement_attempt}/3) after 0.3s...")
                    time.sleep(0.3)
                    image = capture_with_retry(step)  # No additional swipe on retry.
                    ensure_game_connected(cfg, image, on_progress)
                x1, y1, x2, y2 = middle_scan_rectangle(image, cfg)
                first = cv2.cvtColor(previous[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
                second = cv2.cvtColor(image[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
                orb = cv2.ORB_create(nfeatures=1400)
                k1, d1 = orb.detectAndCompute(first, None)
                k2, d2 = orb.detectAndCompute(second, None)
                if d1 is None or d2 is None:
                    stop_reason = "missing landmark descriptors"
                    print("Cannot verify map movement; stopping.")
                    continue
                pairs = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(d1, d2, k=2)
                good = [a for pair in pairs if len(pair) == 2
                        for a, b in [pair] if a.distance < 0.72 * b.distance]
                if len(good) < 12:
                    stop_reason = "too few matching landmarks"
                    print("Too few matching landmarks; stopping:", len(good))
                    continue
                src = np.float32([k1[m.queryIdx].pt for m in good])
                dst = np.float32([k2[m.trainIdx].pt for m in good])
                transform, mask = cv2.estimateAffinePartial2D(
                    src, dst, method=cv2.RANSAC, ransacReprojThreshold=4)
                inliers = int(mask.sum()) if mask is not None else 0
                # A moving map can yield many mismatched ORB pairs despite a
                # substantial, geometrically consistent inlier cluster.
                strong_motion = False
                if transform is not None and mask is not None and inliers >= 80:
                    inlier_offsets = (dst - src)[mask.ravel().astype(bool)]
                    median_offset = np.median(inlier_offsets, axis=0)
                    residual = np.linalg.norm(inlier_offsets - median_offset, axis=1)
                    moving_fraction = float(np.mean(np.linalg.norm(dst - src, axis=1) > 25))
                    strong_motion = (
                        np.median(residual) <= 8
                        and moving_fraction >= .30
                        and abs(float(median_offset[0])) <= 80
                        and (direction == "up" and -950 <= float(median_offset[1]) <= -25
                             or direction == "down" and 25 <= float(median_offset[1]) <= 950)
                        and abs(float(transform[0, 2]) - float(median_offset[0])) <= 20
                        and abs(float(transform[1, 2]) - float(median_offset[1])) <= 20
                    )
                    if strong_motion and inliers / len(good) < .5:
                        print(f"Accepted strong moving-landmark consensus: "
                              f"{inliers}/{len(good)} inliers, "
                              f"median residual {np.median(residual):.1f}px, "
                              f"{moving_fraction:.0%} matches moving.")
                # Secondary coherent vertical movement may be masked by static UI.
                offsets = dst - src
                candidates = offsets[
                    (offsets[:, 1] < -25 if direction == "up" else offsets[:, 1] > 25)
                    & (np.abs(offsets[:, 0]) <= 80)
                    & (np.abs(offsets[:, 1]) <= 950)]
                secondary = None
                if len(candidates) >= 12:
                    for center in candidates:
                        nearby = np.linalg.norm(candidates - center, axis=1) <= 12
                        count = int(nearby.sum())
                        if secondary is None or count > secondary[0]:
                            median = np.median(candidates[nearby], axis=0)
                            residual = np.median(np.linalg.norm(
                                candidates[nearby] - median, axis=1))
                            secondary = (count, median, residual)
                secondary_motion = None
                if secondary is not None:
                    count, median, residual = secondary
                    if count >= 12 and count / len(good) >= .15 and residual <= 6 and abs(median[0]) <= 40:
                        secondary_motion = median
                        print(f"Secondary vertical consensus: {count}/{len(good)} matches, "
                              f"dx={median[0]:.1f}, dy={median[1]:.1f}px.")
                uncertain = (transform is None or inliers < 12 or
                             (inliers / len(good) < .5 and not strong_motion))
                if secondary_motion is not None and (uncertain or
                        (transform is not None and abs(float(transform[1, 2])) < 10)):
                    transform = np.array([[1., 0., float(secondary_motion[0])],
                                          [0., 1., float(secondary_motion[1])]])
                    uncertain = False
                if uncertain:
                    terrain_dy = verify_sparse_vertical_shift(first, second, direction)
                    if terrain_dy is not None:
                        transform = np.array([[1., 0., 0.], [0., 1., terrain_dy]])
                        uncertain = False
                if uncertain:
                    diagnostic_stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
                    before_path = folder / f"column_movement_before_{diagnostic_stamp}.png"
                    after_path = folder / f"column_movement_after_{diagnostic_stamp}.png"
                    cv2.imwrite(str(before_path), previous)
                    cv2.imwrite(str(after_path), image)
                    match_path = folder / f"column_landmarks_{diagnostic_stamp}.png"
                    if mask is not None:
                        selected = [m for m, ok in zip(good, mask.ravel()) if ok]
                    else:
                        selected = good
                    overlay = cv2.drawMatches(
                        first, k1, second, k2, selected[:80], None,
                        flags=cv2.DrawMatchesFlags_NOT_DRAW_SINGLE_POINTS)
                    cv2.imwrite(str(match_path), overlay)
                    displacement = dst - src
                    distances = np.linalg.norm(displacement, axis=1)
                    moving = distances > 25
                    stop_reason = "low-confidence movement"
                    print(f"Low-confidence movement estimate ({inliers}/{len(good)} inliers); stopping.")
                    print(f"Landmark motion check: {int(moving.sum())}/{len(good)} "
                          "matches shifted over 25px.")
                    if transform is not None:
                        print(f"RANSAC candidate shift: dx={transform[0, 2]:.1f}, "
                              f"dy={transform[1, 2]:.1f}px")
                    print("Movement screenshots:", before_path, after_path)
                    print("Matched landmarks:", match_path)
                    continue
                dx, dy = float(transform[0, 2]), float(transform[1, 2])
                print(f"Step {step}: map shifted dx={dx:.1f}, dy={dy:.1f} pixels "
                      f"({inliers}/{len(good)} inliers)")
                if abs(dx) < 10 and abs(dy) < 10:
                    diagnostic_stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
                    before_path = folder / f"column_movement_before_{diagnostic_stamp}.png"
                    after_path = folder / f"column_movement_after_{diagnostic_stamp}.png"
                    match_path = folder / f"column_landmarks_{diagnostic_stamp}.png"
                    cv2.imwrite(str(before_path), previous)
                    cv2.imwrite(str(after_path), image)
                    # Show exactly which landmarks supported the zero-motion estimate.
                    # Coordinates from ORB are local to the cropped map rectangle.
                    inlier_matches = [m for m, ok in zip(good, mask.ravel()) if ok]
                    overlay = cv2.drawMatches(
                        first, k1, second, k2, inlier_matches[:80], None,
                        flags=cv2.DrawMatchesFlags_NOT_DRAW_SINGLE_POINTS)
                    cv2.imwrite(str(match_path), overlay)
                    displacements = dst - src
                    distances = np.linalg.norm(displacements, axis=1)
                    moving = distances > 25
                    print(f"Landmark motion check: {int(moving.sum())}/{len(good)} "
                          "matched landmarks shifted over 25px.")
                    if moving.any():
                        median_move = np.median(displacements[moving], axis=0)
                        print(f"Moving landmark median: dx={median_move[0]:.1f}, "
                              f"dy={median_move[1]:.1f}px")
                    stop_reason = "stationary map / possible boundary"
                    print("Map motion not verified; stopping safely (not a confirmed boundary).")
                    print("Before:", before_path)
                    print("After:", after_path)
                    print("Matched landmarks:", match_path)
                    continue
                if abs(dx) > 80 or (direction == "up" and (dy > -25 or dy < -950)) or (direction == "down" and (dy < 25 or dy > 950)):
                    stop_reason = "unexpected movement"
                    print("Unexpected movement direction or size; stopping.")
                    continue
                movement_verified = True
                break
            if not movement_verified:
                print(f"Movement verification failed after 3 attempts: {stop_reason}.")
                break
        if capture_queue is not None:
            col = cfg.get("_scan_grid_context", {}).get("column", 0)
            path = folder / f"capture_col_{col:03d}_view_{step:03d}.png"
            meta = {"column": col, "view": step,
                    "row": step + 1 if direction == "up" else max_swipes - step + 1,
                    "direction": direction, "captured_at": datetime.now(timezone.utc).isoformat()}
            if cfg.get("_raw_capture_enabled"):
                # Bounded in-memory handoff; the encoding worker writes a durable PNG
                # and metadata before the Ollama worker receives the file path.
                cfg["_enqueue_raw"]((path, image, meta))
            else:
                save_capture_png(cfg, path, image)
                path.with_suffix(".meta.json").write_text(json.dumps(meta), encoding="utf-8")
                ai_queue.put(path)
            completed_views += 1
            print(f"Captured {path.name}; AI processing independently.")
            if step == max_swipes:
                break
            previous = image
            x1, y1, x2, y2 = middle_scan_rectangle(image, cfg)
            cx = (x1 + x2) // 2
            sy, ey = int(y1 + (y2-y1)*.72), int(y1 + (y2-y1)*.32)
            sy, ey = scaled_swipe(sy, ey, vertical_scale, y1, y2)
            if direction == "down":
                sy, ey = ey, sy
            if on_progress:
                on_progress(step, "swipe_pending")
            adb(cfg, "shell", "input", "swipe",
                str(cx), str(sy), str(cx), str(ey), str(swipe_ms))
            time.sleep(settle)
            if on_progress:
                on_progress(step + 1, "view")
            continue
        print(f"Analyzing map view {step + 1} of {max_swipes + 1}...")
        players = None
        last_ai_error = None
        for ai_attempt in range(1, 4):
            try:
                # Reuse the captured image: retries must not move the map or
                # change the grid position associated with this observation.
                players = debug_ollama(cfg, image=image)
                if ai_attempt > 1:
                    print(f"Map view {step + 1}: Ollama succeeded on attempt {ai_attempt}/3.")
                break
            except (RuntimeError, OSError, TimeoutError, ValueError) as exc:
                last_ai_error = exc
                print(f"Map view {step + 1}: Ollama attempt {ai_attempt}/3 failed: {exc}")
                if ai_attempt < 3:
                    time.sleep(1.5)
        if players is None:
            print(f"Map view {step + 1}: trying overlapping split-image fallback.")
            try:
                players = analyze_split_fallback(cfg, image)
            except (RuntimeError, OSError, TimeoutError, ValueError) as exc:
                last_ai_error = exc
                print(f"Split-image fallback failed: {exc}")
        if players is None:
            failed_views += 1
            consecutive_failures += 1
            print(f"Map view {step + 1} analysis failed after 3 attempts: {last_ai_error}")
            # Keep the screenshot for later inspection/reprocessing. A vision
            # failure must not prevent movement verification or the next swipe.
            failure_stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
            failure_path = folder / f"column_unanalyzed_{failure_stamp}.png"
            cv2.imwrite(str(failure_path), image)
            context = cfg.get("_scan_grid_context", {})
            metadata = {
                "column": context.get("column"),
                "view": step,
                "row": (step + 1 if direction == "up"
                        else max_swipes - step + 1),
                "direction": direction,
                "max_swipes": max_swipes,
                "captured_at": datetime.now().astimezone().isoformat(),
            }
            failure_path.with_suffix(".meta.json").write_text(
                json.dumps(metadata, indent=2), encoding="utf-8")
            print(f"Unanalyzed screenshot saved: {failure_path}")
            previous_players = []
            if consecutive_failures >= 5:
                stop_reason = "five consecutive Ollama failures"
                print("Five consecutive Ollama failures; stopping safely.")
                break
            if step == max_swipes:
                break
            previous = image
            x1, y1, x2, y2 = middle_scan_rectangle(image, cfg)
            cx = (x1 + x2) // 2
            sy = int(y1 + (y2 - y1) * .72)
            ey = int(y1 + (y2 - y1) * .32)
            if direction == "down":
                sy, ey = ey, sy
            print(f"Continuing navigation after AI failure: {direction} swipe "
                  f"{step + 1} of {max_swipes}...")
            if on_progress:
                on_progress(step, "swipe_pending")
            adb(cfg, "shell", "input", "swipe",
                str(cx), str(sy), str(cx), str(ey), str(swipe_ms))
            time.sleep(settle)
            if on_progress:
                on_progress(step + 1, "view")
            continue
        consecutive_failures = 0
        current_players = []
        matched_previous = set()
        for player in players:
            if not isinstance(player, dict):
                continue
            name = player.get("username")
            if not valid_scanned_username(name):
                print(f"Ignoring invalid OCR username: {name!r}")
                continue
            if is_ignored_commander(player):
                print(f"Ignoring default Commander2 username: {name!r}")
                continue
            if not any(ch.isalpha() for ch in name):
                print(f"Ignoring non-name candidate: {name!r}")
                continue
            key = (str(player.get("guild") or "").casefold(), name.strip().casefold())
            box = player.get("box")
            valid_box = (isinstance(box, list) and len(box) == 4
                         and all(isinstance(v, (int, float)) for v in box)
                         and box[2] > box[0] and box[3] > box[1])
            matched_key = None
            if dx is not None:
                candidates = []
                for i, (prior, prior_key) in enumerate(previous_players):
                    if i in matched_previous:
                        continue
                    old_guild = str(prior.get("guild") or "").casefold()
                    new_guild = str(player.get("guild") or "").casefold()
                    if old_guild and new_guild and old_guild != new_guild:
                        continue
                    old_name = str(prior.get("username") or "").casefold()
                    similarity = SequenceMatcher(None, old_name, name.strip().casefold()).ratio()
                    old_box = prior.get("box")
                    distance = None
                    if valid_box and isinstance(old_box, list) and len(old_box) == 4 and all(
                            isinstance(v, (int, float)) for v in old_box):
                        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
                        predicted_x = (old_box[0] + old_box[2]) / 2 + dx
                        predicted_y = (old_box[1] + old_box[3]) / 2 + dy
                        distance = ((cx - predicted_x) ** 2 + (cy - predicted_y) ** 2) ** .5
                    near = distance is not None and distance <= 100
                    # Strong names can survive unreliable model-generated boxes.
                    # Weaker names require corroborating spatial evidence.
                    if similarity >= .88 or (near and similarity >= .70):
                        candidates.append((similarity, distance, i, prior_key))
                candidates.sort(key=lambda c: (-c[0], c[1] if c[1] is not None else 1e9))
                if candidates and (len(candidates) == 1 or
                                   candidates[0][0] - candidates[1][0] >= .12):
                    similarity, distance, i, matched_key = candidates[0]
                    matched_previous.add(i)
                    old_level = previous_players[i][0].get("level")
                    new_level = player.get("level")
                    if old_level != new_level:
                        print(f"Conflicting unverified levels for {name!r}: "
                              f"{old_level!r} vs {new_level!r}")
                    if matched_key != key:
                        print(f"Likely repeat: {name!r} -> "
                              f"{previous_players[i][0]['username']!r} "
                              f"(name similarity {similarity:.2f}, "
                              f"position offset {distance if distance is not None else 'unknown'})")
            if matched_key is None and key in seen:
                matched_key = key
            canonical_key = matched_key if matched_key is not None else key
            if canonical_key not in seen:
                seen.add(canonical_key)
                observations.append({"view": step, **player})
                if on_player is not None:
                    on_player(player, step)
            current_players.append((player, canonical_key))
        previous_players = current_players
        completed_views += 1
        print(f"Unique provisional players so far: {len(seen)}")
        if step == max_swipes:
            break
        previous = image
        x1, y1, x2, y2 = middle_scan_rectangle(image, cfg)
        cx = (x1 + x2) // 2
        sy = int(y1 + (y2-y1)*.72)
        ey = int(y1 + (y2-y1)*.32)
        if direction == "down":
            sy, ey = ey, sy
        print(f"Performing {direction} swipe {step + 1} of {max_swipes}...")
        if on_progress:
            on_progress(step, "swipe_pending")
        adb(cfg, "shell", "input", "swipe",
            str(cx), str(sy), str(cx), str(ey), str(swipe_ms))
        time.sleep(settle)
        if on_progress:
            on_progress(step + 1, "view")
    path = folder / f"column_scan_{stamp}.json"
    path.write_text(json.dumps(observations, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    print(f"Saved {len(observations)} unique provisional observations:", path)
    print(f"Scan finished: {completed_views} analyzed views, "
          f"{failed_views} unanalyzed views; reason: {stop_reason}.")
    print("Read-only test complete; no player database writes or base clicks.")
    return stop_reason, step


def calibrate_movement(cfg):
    """One vertical swipe; compare before/after images without touching database."""
    before = screenshot(cfg)
    height, width = before.shape[:2]
    x1, y1, x2, y2 = middle_scan_rectangle(before, cfg)
    cx = (x1 + x2) // 2
    start_y = int(y1 + (y2-y1)*0.72)
    end_y = int(y1 + (y2-y1)*0.32)
    print("One upward finger swipe to move map downward.")
    print("Swipe:", (cx, start_y), "to", (cx, end_y))
    adb(cfg, "shell", "input", "swipe", str(cx), str(start_y),
        str(cx), str(end_y), "650")
    time.sleep(1.5)
    after = screenshot(cfg)
    folder = scan_diagnostic_folder(cfg)
    stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
    before_path = folder / f"movement_before_{stamp}.png"
    after_path = folder / f"movement_after_{stamp}.png"
    cv2.imwrite(str(before_path), before)
    cv2.imwrite(str(after_path), after)
    # Compare central terrain features using RANSAC; UI and animations can
    # create false matches, so report a confidence indicator.
    gray1 = cv2.cvtColor(before[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
    gray2 = cv2.cvtColor(after[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
    orb = cv2.ORB_create(nfeatures=1200)
    k1, d1 = orb.detectAndCompute(gray1, None)
    k2, d2 = orb.detectAndCompute(gray2, None)
    if d1 is None or d2 is None:
        print("Not enough visual features to estimate movement.")
    else:
        pairs = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(d1, d2, k=2)
        good = [a for pair in pairs if len(pair) == 2
                for a, b in [pair] if a.distance < 0.72*b.distance]
        if len(good) < 8:
            print("Insufficient feature matches:", len(good))
        else:
            src = np.float32([k1[m.queryIdx].pt for m in good])
            dst = np.float32([k2[m.trainIdx].pt for m in good])
            matrix, inliers = cv2.estimateAffinePartial2D(
                src, dst, method=cv2.RANSAC, ransacReprojThreshold=4)
            if matrix is None:
                print("Movement estimation failed.")
            else:
                dx, dy = float(matrix[0, 2]), float(matrix[1, 2])
                count = int(inliers.sum()) if inliers is not None else 0
                print(f"Terrain screen displacement: dx={dx:.1f}px dy={dy:.1f}px")
                print(f"Inliers: {count}/{len(good)}")
                if count < 10 or count/len(good) < 0.45:
                    print("LOW CONFIDENCE: do not use this estimate for navigation.")
                elif abs(dy) < 8 and abs(dx) < 8:
                    print("Little movement detected; possibly at a hard boundary.")
                else:
                    print("Movement detected; repeat at a different map position to validate.")
    print("Before:", before_path)
    print("After:", after_path)
    print("Calibration only: one swipe, no base clicks or database writes.")


def benchmark_screenshot(cfg, samples=10):
    """Compare PNG and raw ADB framebuffer capture without moving the map."""
    if not 1 <= samples <= 100:
        raise ValueError("samples must be between 1 and 100")
    import struct
    results = {}
    reference = None
    for mode in ("png", "raw"):
        timings = []
        for i in range(samples):
            started = time.perf_counter()
            if mode == "png":
                payload = adb(cfg, "exec-out", "screencap", "-p")
                image = cv2.imdecode(np.frombuffer(payload, np.uint8), cv2.IMREAD_COLOR)
            else:
                payload = adb(cfg, "exec-out", "screencap")
                if len(payload) < 12:
                    raise RuntimeError("Raw framebuffer header is incomplete")
                width, height, pixel_format = struct.unpack_from("<III", payload)
                if not (0 < width <= 8192 and 0 < height <= 8192):
                    raise RuntimeError(f"Unexpected raw dimensions: {width}x{height}")
                channels = {1: 4, 2: 4, 3: 3}.get(pixel_format)
                if channels is None:
                    raise RuntimeError(f"Unsupported Android pixel format: {pixel_format}")
                expected = width * height * channels
                offset = len(payload) - expected
                if offset not in (12, 16):
                    raise RuntimeError(f"Unexpected framebuffer payload length/header: {len(payload)}/{offset}")
                pixels = np.frombuffer(payload, dtype=np.uint8, count=expected, offset=offset)
                pixels = pixels.reshape((height, width, channels))
                image = cv2.cvtColor(pixels, cv2.COLOR_RGBA2BGR if channels == 4 else cv2.COLOR_RGB2BGR)
            elapsed = time.perf_counter() - started
            if image is None:
                raise RuntimeError(f"{mode} screenshot decode failed")
            if reference is None:
                reference = image.shape
            if image.shape != reference:
                raise RuntimeError(f"Screenshot dimensions differ: {image.shape} vs {reference}")
            timings.append(elapsed)
            print(f"{mode.upper()} {i+1}/{samples}: {elapsed:.3f}s, {len(payload)/1048576:.2f} MiB")
        results[mode] = sum(timings) / len(timings)
    print(f"Average PNG: {results['png']:.3f}s; raw: {results['raw']:.3f}s")
    print("Benchmark only: production screenshot capture is unchanged.")


def calibrate_capture_ai(cfg, samples=3):
    """Compare PNG and raw captures, PNG save time, and Ollama name reading."""
    if not 1 <= samples <= 10:
        raise ValueError("samples must be between 1 and 10")
    import struct
    folder = ROOT / "screenshots" / ("capture_ai_" + datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f"))
    folder.mkdir(parents=True, exist_ok=True)
    report = []
    for i in range(samples):
        for mode in ("png", "raw"):
            print(f"Pair {i+1}/{samples} {mode.upper()}: starting capture...", flush=True)
            try:
                started = time.perf_counter()
                if mode == "png":
                    payload = adb(cfg, "exec-out", "screencap", "-p")
                    image = cv2.imdecode(np.frombuffer(payload, np.uint8), cv2.IMREAD_COLOR)
                else:
                    payload = adb(cfg, "exec-out", "screencap")
                    if len(payload) < 12:
                        raise ValueError("Incomplete raw framebuffer")
                    width, height, fmt = struct.unpack_from("<III", payload)
                    if not (0 < width <= 8192 and 0 < height <= 8192):
                        raise ValueError(f"Invalid framebuffer size: {width}x{height}")
                    channels = {1: 4, 2: 4, 3: 3}.get(fmt)
                    if channels is None:
                        raise ValueError(f"Unsupported framebuffer format: {fmt}")
                    expected = width * height * channels
                    offset = len(payload) - expected
                    if offset not in (12, 16):
                        raise ValueError(f"Invalid framebuffer header size: {offset}")
                    pixels = np.frombuffer(payload, np.uint8, count=expected, offset=offset).reshape(height, width, channels)
                    image = cv2.cvtColor(pixels, cv2.COLOR_RGBA2BGR if channels == 4 else cv2.COLOR_RGB2BGR)
                capture_time = time.perf_counter() - started
                print(f"Pair {i+1} {mode.upper()}: captured in {capture_time:.3f}s; checking and saving...", flush=True)
                if image is None:
                    raise ValueError("Capture decoding failed")
                ensure_game_connected(cfg, image)
                path = folder / f"pair_{i+1:02d}_{mode}.png"
                started = time.perf_counter()
                if mode == "png":
                    path.write_bytes(payload)
                elif not cv2.imwrite(str(path), image):
                    raise RuntimeError("PNG encoding failed")
                save_time = time.perf_counter() - started
                saved = cv2.imread(str(path))
                if saved is None or saved.shape != image.shape or not np.array_equal(saved, image):
                    raise RuntimeError("Saved PNG differs from captured image")
                print(f"Pair {i+1} {mode.upper()}: saved in {save_time:.3f}s; requesting Ollama (up to 180s)...", flush=True)
                started = time.perf_counter()
                players = debug_ollama(cfg, image=saved)
                ai_time = time.perf_counter() - started
                entry = {"pair": i+1, "mode": mode, "capture_seconds": round(capture_time, 3),
                         "save_seconds": round(save_time, 3), "ai_seconds": round(ai_time, 3),
                         "names": [p.get("username") if isinstance(p, dict) else str(p) for p in players],
                         "image": path.name, "status": "ok"}
                print(f"Pair {i+1} {mode.upper()}: capture={capture_time:.3f}s save={save_time:.3f}s "
                      f"AI={ai_time:.2f}s names={len(players)}: {entry['names']}")
            except Exception as exc:
                entry = {"pair": i+1, "mode": mode, "status": "failed", "error": str(exc)}
                print(f"Pair {i+1} {mode.upper()} FAILED: {exc}", flush=True)
            report.append(entry)
            (folder / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Calibration results: {folder}")
    print("No map swipes, database writes, or production capture changes.")


def benchmark_capture(cfg, swipes=110, settle=0.2, swipe_ms=250):
    """Measure capture throughput and map displacement; no Ollama or DB writes."""
    if not 1 <= swipes <= 500:
        raise ValueError("swipes must be between 1 and 500")
    if not 0 <= settle <= 3:
        raise ValueError("settle must be between 0 and 3 seconds")
    if not 10 <= swipe_ms <= 1000:
        raise ValueError("swipe-ms must be between 10 and 1000")
    folder = ROOT / "screenshots" / ("calibration_" + datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f"))
    folder.mkdir(parents=True, exist_ok=True)
    before = screenshot(cfg)
    ensure_game_connected(cfg, before)
    x1, y1, x2, y2 = middle_scan_rectangle(before, cfg)
    cx = (x1 + x2) // 2
    sy, ey = int(y1 + (y2-y1)*.72), int(y1 + (y2-y1)*.32)
    orb = cv2.ORB_create(nfeatures=1400)
    results = []
    cv2.imwrite(str(folder / "view_000.png"), before)
    for n in range(1, swipes + 1):
        started = time.perf_counter()
        adb(cfg, "shell", "input", "swipe", str(cx), str(sy), str(cx), str(ey), str(swipe_ms))
        swipe_seconds = time.perf_counter() - started
        time.sleep(settle)
        started_capture = time.perf_counter()
        after = screenshot(cfg)
        capture_seconds = time.perf_counter() - started_capture
        ensure_game_connected(cfg, after)
        cv2.imwrite(str(folder / f"view_{n:03d}.png"), after)
        first = cv2.cvtColor(before[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
        second = cv2.cvtColor(after[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
        k1, d1 = orb.detectAndCompute(first, None)
        k2, d2 = orb.detectAndCompute(second, None)
        dx = dy = None
        inliers = 0
        matches = 0
        if d1 is not None and d2 is not None:
            pairs = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(d1, d2, k=2)
            good = [a for pair in pairs if len(pair) == 2 for a, b in [pair]
                    if a.distance < .72 * b.distance]
            matches = len(good)
            if matches >= 12:
                src = np.float32([k1[m.queryIdx].pt for m in good])
                dst = np.float32([k2[m.trainIdx].pt for m in good])
                matrix, mask = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=4)
                if matrix is not None and mask is not None:
                    inliers = int(mask.sum())
                    if inliers >= 12 and inliers / matches >= .45:
                        dx, dy = float(matrix[0, 2]), float(matrix[1, 2])
        row = {"swipe": n, "swipe_seconds": round(swipe_seconds, 3),
               "capture_seconds": round(capture_seconds, 3),
               "settle_seconds": settle, "dx": dx, "dy": dy,
               "matches": matches, "inliers": inliers}
        results.append(row)
        print(f"Calibration {n}/{swipes}: swipe={swipe_seconds:.2f}s capture={capture_seconds:.2f}s "
              f"displacement=({dx},{dy}) inliers={inliers}/{matches}")
        before = after
        if dx is not None and abs(dy) < 8 and abs(dx) < 8:
            print("Stationary frame observed; continuing benchmark (not a confirmed boundary).")
    (folder / "measurements.json").write_text(json.dumps({
        "scan_region": [x1,y1,x2,y2], "swipe_duration_ms": swipe_ms,
        "results": results}, indent=2), encoding="utf-8")
    if results:
        mean_swipe = sum(r["swipe_seconds"] for r in results) / len(results)
        mean_capture = sum(r["capture_seconds"] for r in results) / len(results)
        print(f"Average swipe={mean_swipe:.3f}s capture={mean_capture:.3f}s "
              f"settle={settle:.3f}s total={mean_swipe+mean_capture+settle:.3f}s/view")
    print(f"Calibration results: {folder}")
    print("Inspect displacement confidence and screenshots before changing scan spacing.")


def valid_scanned_username(name):
    """Game usernames cannot contain whitespace; reject OCR false positives."""
    return (isinstance(name, str) and bool(name.strip())
            and not any(char.isspace() for char in name)
            and not (name.strip().isdigit() and 1 <= int(name.strip()) <= 99)
            and any(char.isalpha() for char in name))


def is_ignored_commander(player):
    """Exclude default Commander2 usernames, including embedded guild prefixes."""
    if not isinstance(player, dict):
        return False
    name = player.get("username")
    if not isinstance(name, str):
        return False
    normalized = name.strip()
    normalized = re.sub(r"^\[[^\]\r\n]{1,12}\]\s*", "", normalized)
    normalized = re.sub(r"^[A-Za-z0-9]{2,8}[!|:]\\s+", "", normalized)
    return normalized.casefold().startswith("commander2")


def debug_ollama(cfg, image=None, crop_override=None):
    """Read-only screenshot analysis using a local Ollama vision model."""
    if image is None:
        image = screenshot(cfg)
    x1, y1, x2, y2 = middle_scan_rectangle(image, cfg)
    if crop_override is not None:
        x1, y1, x2, y2 = crop_override
    crop = image[y1:y2, x1:x2]
    if crop.size == 0:
        raise ValueError("Empty Ollama image crop")
    ok, png = cv2.imencode(".png", crop)
    if not ok:
        raise RuntimeError("Could not encode screenshot")
    request_data = {
        "model": cfg.get("ollama", {}).get("model", "qwen3-vl:4b-instruct"),
        "stream": False,
        "think": False,
        "format": {
            "type": "object",
            "properties": {
                "players": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 20,
                    "uniqueItems": True
                }
            },
            "required": ["players"],
            "additionalProperties": False
        },
        "keep_alive": cfg.get("ollama", {}).get("keep_alive", "30m"),
        "messages": [
            {"role": "user", "content": 'Find usernames belonging to stationary PLAYER BASES/CITIES on the world map, not every nameplate. IMPORTANT: Ignore transport trucks, cargo trucks, supply vehicles, moving convoys, marching troops, resource transports, and any name floating above those vehicles, EVEN IF it looks like a normal [guild]Username tag. A truck with a dark rectangular nameplate is NOT a player base; exclude its name. Only include a name when it is visibly associated with a stationary player base/city, not a truck or other map object. If uncertain whether a name belongs to a base versus a vehicle, omit it. Return ONLY a JSON object {"players":[...]} with unique player-name strings (maximum 20), preserving visible guild tags. If only transport trucks or no identifiable player bases are visible, return {"players":[]}. Do not include levels, explanations, or additional keys.',
             "images": [base64.b64encode(png.tobytes()).decode("ascii")]}
        ],
        "options": {"temperature": 0, "num_predict": cfg.get("ollama", {}).get("num_predict", 512)}
    }
    url = "http://127.0.0.1:11434/api/chat"
    req = urllib.request.Request(url,
        data=json.dumps(request_data).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as response:
        answer = json.load(response)
    content = (answer.get("message") or {}).get("content") or ""
    try:
        if not answer.get("done", False) or not content.strip():
            raise ValueError("Ollama response incomplete or empty")
        cleaned = content.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if len(lines) >= 3 and lines[-1].strip() == "```":
                cleaned = "\n".join(lines[1:-1]).strip()
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict) and isinstance(parsed.get("error"), str) and any(phrase in parsed["error"].casefold() for phrase in ("no player names found", "no visible player names found")):
            players = []
        elif isinstance(parsed, list):
            players = parsed
        elif isinstance(parsed, dict) and isinstance(parsed.get("players"), list):
            players = parsed["players"]
        elif isinstance(parsed, dict) and isinstance(parsed.get("player_names"), list):
            players = parsed["player_names"]
        elif isinstance(parsed, dict) and isinstance(parsed.get("visible_player_names"), list):
            players = parsed["visible_player_names"]
        elif isinstance(parsed, dict) and isinstance(parsed.get("names"), list):
            players = parsed["names"]
        elif isinstance(parsed, dict) and parsed and all(
            isinstance(k, str) and isinstance(v, (str, int))
            and (str(v).strip() == "" or str(v).isdigit())
            for k, v in parsed.items()
        ):
            players = [{"nameplate": k, "level": int(v) if str(v).isdigit() else None}
                       for k, v in parsed.items()]
        elif isinstance(parsed, dict) and parsed and all(
            isinstance(k, str) and isinstance(v, list) and len(v) == 1
            and isinstance(v[0], int) and not isinstance(v[0], bool)
            for k, v in parsed.items()
        ):
            # Qwen sometimes maps each nameplate to a one-element level array.
            players = [{"nameplate": name, "level": level[0]}
                       for name, level in parsed.items()]
        elif isinstance(parsed, dict) and len(parsed) == 1 and all(
            isinstance(k, str) and isinstance(v, list) and all(isinstance(n, str) for n in v)
            for k, v in parsed.items()
        ):
            # Some vision responses put the first name in the object key.
            first_name, remaining_names = next(iter(parsed.items()))
            players = [first_name, *remaining_names]
        else:
            raise ValueError("Ollama response must be a player list or object with players array")
    except (ValueError, json.JSONDecodeError) as exc:
        folder = scan_diagnostic_folder(cfg)
        stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
        path = folder / f"ollama_invalid_{stamp}.json"
        path.write_text(json.dumps({
            "response": answer,
            "model": request_data["model"],
            "image_dimensions": [crop.shape[1], crop.shape[0]]
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        raise RuntimeError(
            f"Ollama failed to complete screenshot analysis (done={answer.get('done')!r}). "
            f"Diagnostic saved to {path}. No swipe performed."
        ) from exc
    # Accept repeated names from valid JSON; deduplicate them before normalization.
    # Keep the first occurrence, preserving the original name spelling and order.
    deduplicated = []
    seen_raw = set()
    for item in players:
        if isinstance(item, str):
            name = item.strip()
        elif isinstance(item, dict):
            name = str(item.get("nameplate") or item.get("username") or "").strip()
        else:
            continue
        if not name:
            continue
        key = name.casefold()
        if key in seen_raw:
            continue
        seen_raw.add(key)
        deduplicated.append(item)
    if len(deduplicated) != len(players):
        print(f"Ollama duplicate names removed: {len(players) - len(deduplicated)}")
    players = deduplicated
    # Split the optional [guild] prefix deterministically in Python.
    normalized = []
    seen_names = set()
    for item in players:
        if isinstance(item, str):
            raw_name = item.strip()
        elif isinstance(item, dict):
            raw_name = str(item.get("nameplate") or item.get("username") or "").strip()
            if item.get("guild") and not raw_name.startswith("["):
                raw_name = f"[{item['guild']}] {raw_name}"
        else:
            continue
        match = re.match(r"^\[([^\]\r\n]{1,12})\]\s*(.+)$", raw_name)
        guild = match.group(1).strip() if match else None
        username = match.group(2).strip() if match else raw_name
        if not valid_scanned_username(username) or username.casefold().startswith("commander2"):
            continue
        identity = (guild or "", username.casefold())
        if identity in seen_names:
            continue
        seen_names.add(identity)
        normalized.append({"username": username, "guild": guild, "level": None, "box": None})
    players = normalized
    print("Ollama raw player candidates:", len(players))
    for player in players:
        if not isinstance(player, dict):
            continue
        name = player.get("username")
        if not isinstance(name, str):
            continue
        # Vision models often include the guild tag inside username.
        match = re.match(r"^\[([A-Za-z0-9]{2,8})\]\s*(.+)$", name.strip())
        if match:
            player["guild"] = match.group(1)
            player["username"] = match.group(2).strip()
        print(player)
    folder = scan_diagnostic_folder(cfg)
    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
    path = folder / f"ollama_raw_{timestamp}.json"
    path.write_text(json.dumps(players, indent=2, ensure_ascii=False), encoding="utf-8")
    print("Saved raw results:", path)
    print("Unverified AI output. No database writes or automated clicks.")
    return players


def analyze_split_fallback(cfg, image):
    """Try two overlapping horizontal crops of the same map view."""
    x1, y1, x2, y2 = middle_scan_rectangle(image, cfg)
    height = y2 - y1
    if height < 80:
        raise ValueError("Map crop too short for split fallback")
    midpoint = (y1 + y2) // 2
    overlap = max(30, int(height * .15))
    regions = [
        (x1, y1, x2, min(y2, midpoint + overlap)),
        (x1, max(y1, midpoint - overlap), x2, y2),
    ]
    combined = []
    seen = set()
    errors = []
    for index, region in enumerate(regions, 1):
        try:
            candidates = debug_ollama(cfg, image=image, crop_override=region)
            for player in candidates:
                if not isinstance(player, dict):
                    continue
                name = player.get("username")
                if not valid_scanned_username(name) or is_ignored_commander(player):
                    continue
                key = name.casefold()
                if key not in seen:
                    seen.add(key)
                    combined.append(player)
        except (RuntimeError, OSError, TimeoutError, ValueError) as exc:
            errors.append(str(exc))
            print(f"Split crop {index}/2 failed: {exc}")
    if len(errors) == len(regions):
        raise RuntimeError("Both split crops failed: " + "; ".join(errors))
    print(f"Split fallback recovered {len(combined)} unique valid candidates.")
    return combined


def debug_nameplates(cfg):
    """Write an annotated image; no base clicks or database writes."""
    image = screenshot(cfg)
    output = image.copy()
    masks = ui_mask_rectangles(image, cfg)
    safe_top, safe_bottom = safe_scan_bounds(image, cfg)
    scan_x1, scan_y1, scan_x2, scan_y2 = middle_scan_rectangle(image, cfg)
    # Preserve OCR context around nameplates; safe bounds apply to final groups,
    # not individual tokens (which may extend outside a clickable nameplate).
    candidates = nameplate_candidates(image,
        cfg.get("ocr", {}).get("bottom_exclusion_ratio", 0.09),
        cfg.get("ocr", {}).get("top_exclusion_ratio", 0.08), masks)
    groups = combined_player_candidates(image, candidates, cfg)
    for group in groups:
        x1, y1, x2, y2 = group["box"]
        color = (255, 0, 255) if group.get("source") == "dark-strip" else ((0, 255, 0) if group["guild"] else (255, 165, 0))
        cv2.rectangle(output, (x1, y1), (x2, y2), color, 2)
        if group["level"] is not None:
            cv2.putText(output, "Lv." + str(group["level"]), (x1, min(image.shape[0]-4, y2+34)),
                        cv2.FONT_HERSHEY_SIMPLEX, .55, (0, 255, 0), 2)
    # Diagnostics show the actual acceptance window, not every OCR token.
    cv2.rectangle(output, (scan_x1, scan_y1), (scan_x2, scan_y2), (0, 0, 255), 2)
    # Dim the excluded screen area to make the active region unmistakable.
    overlay = output.copy()
    shade = (35, 35, 35)
    cv2.rectangle(overlay, (0, 0), (image.shape[1], scan_y1), shade, -1)
    cv2.rectangle(overlay, (0, scan_y2), (image.shape[1], image.shape[0]), shade, -1)
    cv2.rectangle(overlay, (0, scan_y1), (scan_x1, scan_y2), shade, -1)
    cv2.rectangle(overlay, (scan_x2, scan_y1), (image.shape[1], scan_y2), shade, -1)
    output = cv2.addWeighted(overlay, 0.65, output, 0.35, 0)
    cv2.rectangle(output, (scan_x1, scan_y1), (scan_x2, scan_y2), (0, 0, 255), 2)
    folder = scan_diagnostic_folder(cfg)
    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
    path = folder / f"nameplate_candidates_{timestamp}.png"
    if not cv2.imwrite(str(path), output):
        raise RuntimeError(f"Failed to save annotated screenshot: {path}")
    print(f"Safe scan area: y={safe_top}..{safe_bottom} (height={image.shape[0]})")
    print("Middle scan region:", (scan_x1, scan_y1, scan_x2, scan_y2))
    print("OCR text candidates:", len(candidates))
    print("Grouped player candidates:", len(groups))
    print("Dark-strip candidates:", sum(g["source"] == "dark-strip" for g in groups))
    for group in groups:
        print("  [{}] {} confidence={} level={} source={} box={}".format(
            group["guild"], group["username"], group["confidence"],
            group["level"], group["source"], group["box"]))
    print("Annotated screenshot:", path)
    for x, y, w, h, token, confidence in candidates:
        if "[" in token or "]" in token or re.search(r"D3AD", token, re.I):
            print(f"Candidate {token!r} at ({x},{y}) confidence={confidence:.0f}")
    print("Note: boxes are text candidates, not verified player bases.")


def connect(cfg):
    exe = cfg.get("adb_path") or "adb"
    serial = cfg.get("adb_serial") or "127.0.0.1:5555"
    result = subprocess.run([exe, "connect", serial], check=True,
                            capture_output=True, text=True, timeout=20)
    print(result.stdout.strip())
    print("Device:", adb(cfg, "get-state").decode().strip())


def test(cfg):
    connect(cfg)
    image = screenshot(cfg)
    folder = scan_diagnostic_folder(cfg)
    path = folder / "test.png"
    cv2.imwrite(str(path), image)
    print("Screenshot:", path, "resolution:", image.shape[1], image.shape[0])
    print("OCR output:\n", recognize(image))


def record(db, server, username, tag, x=None, y=None, evidence=""):
    """Store a verified observation; usernames are provisional identities."""
    now = datetime.now(timezone.utc).isoformat()
    with db:
        guild_id = None
        if tag:
            db.execute("INSERT OR IGNORE INTO guilds(server,tag) VALUES(?,?)",
                       (server, tag))
            guild_id = db.execute(
                "SELECT id FROM guilds WHERE server=? AND tag=?",
                (server, tag)).fetchone()[0]
        db.execute("""INSERT INTO players(server,username,guild_id,x,y,last_seen)
          VALUES(?,?,?,?,?,?) ON CONFLICT(server,username) DO UPDATE SET
          guild_id=excluded.guild_id, x=excluded.x, y=excluded.y,
          last_seen=excluded.last_seen""",
                   (server, username, guild_id, x, y, now))
        player_id = db.execute(
            "SELECT id FROM players WHERE server=? AND username=?",
            (server, username)).fetchone()[0]
        db.execute("""INSERT INTO observations(player_id,observed_at,x,y,guild_id,evidence)
          VALUES(?,?,?,?,?,?)""", (player_id, now, x, y, guild_id, evidence))
        if guild_id:
            last = db.execute("""SELECT id,guild_id FROM guild_memberships
              WHERE player_id=? ORDER BY id DESC LIMIT 1""",
                              (player_id,)).fetchone()
            if last and last[1] == guild_id:
                db.execute("UPDATE guild_memberships SET last_seen=? WHERE id=?",
                           (now, last[0]))
            else:
                db.execute("""INSERT INTO guild_memberships
                  (player_id,guild_id,first_seen,last_seen) VALUES(?,?,?,?)""",
                           (player_id, guild_id, now, now))



def process_capture_ai(cfg, path, unique_players, save_players):
    """Process a durable capture; failures remain retryable without navigating."""
    result_path = path.with_suffix(".players.json")
    failure_path = path.with_suffix(".failed.json")
    if result_path.exists():
        return "skipped"
    try:
        image = cv2.imread(str(path))
        if image is None:
            raise RuntimeError(f"Unreadable screenshot: {path}")
        players = None
        last_error = None
        # One fast pass in the background worker. Preserve failed captures
        # for a later retry rather than blocking the growing capture queue.
        players = debug_ollama(cfg, image=image)
        if not isinstance(players, list):
            raise ValueError("AI response is not a list of players")
        meta = json.loads(path.with_suffix(".meta.json").read_text(encoding="utf-8"))
        for field in ("row", "column", "view", "direction", "captured_at"):
            if field not in meta:
                raise ValueError(f"Capture metadata missing {field}")
        added = 0
        for player in players:
            if not isinstance(player, dict):
                continue
            name = player.get("username")
            if not valid_scanned_username(name) or is_ignored_commander(player):
                continue
            key = name.strip().casefold()
            if key in unique_players:
                continue
            unique_players[key] = {
                "username": name.strip(), "guild": str(player.get("guild") or ""),
                "level": player.get("level") if player.get("level") is not None else "",
                "row": min(int(meta["row"]), 60), "col": min(int(meta["column"]), 150), "view": meta["view"],
                "direction": meta["direction"], "observed_at": meta["captured_at"],
                "coordinate_type": "approximate swipe grid"}
            added += 1
        if added:
            save_players()
        result_path.write_text(json.dumps({"players": players, "metadata": meta},
                                          ensure_ascii=False, indent=2), encoding="utf-8")
        failure_path.unlink(missing_ok=True)
        print(f"AI completed {path.name}: {len(players)} candidates, {added} new players.")
        return "completed"
    except Exception as exc:
        failure_path.write_text(json.dumps({
            "screenshot": path.name, "error": str(exc),
            "failed_at": datetime.now(timezone.utc).isoformat(),
        }, indent=2), encoding="utf-8")
        print(f"AI failed {path.name}: {exc}; retained for offline retry.")
        return "failed"


def retry_failed_after_scan(cfg, folder, unique_players, save_players):
    """Retry each failed capture once after the initial AI queue has drained."""
    failures = sorted(p for p in folder.glob("capture_col_*_view_*.png")
                      if p.with_suffix(".failed.json").exists()
                      and not p.with_suffix(".players.json").exists()
                      and not p.with_suffix(".final-retried.json").exists())
    print(f"Final AI retry: {len(failures)} failed screenshots eligible for one retry.")
    recovered = 0
    for index, path in enumerate(failures, 1):
        # Write marker first so interrupted sessions cannot retry indefinitely.
        marker = path.with_suffix(".final-retried.json")
        marker.write_text(json.dumps({
            "attempted_at": datetime.now(timezone.utc).isoformat(),
            "reason": "one automatic retry after all captures were processed",
        }, indent=2), encoding="utf-8")
        outcome = process_capture_ai(cfg, path, unique_players, save_players)
        if outcome == "completed":
            recovered += 1
        print(f"Final retry {index}/{len(failures)}: {outcome} ({path.name})")
    print(f"Final AI retry finished: {recovered}/{len(failures)} recovered.")
    capture_ai_report(folder)


def publish_scan_csv(folder, threshold=90.0, branch="main"):
    """Publish a sufficiently analyzed session without merging scanner code."""
    import shutil
    import tempfile

    captures = list(folder.glob("capture_col_*_view_*.png"))
    completed = sum(p.with_suffix(".players.json").exists() for p in captures)
    failed = sum(p.with_suffix(".failed.json").exists() and
                 not p.with_suffix(".players.json").exists() for p in captures)
    pending = len(captures) - completed - failed
    rate = 100 * completed / len(captures) if captures else 0.0
    checkpoint = ROOT / "exports" / "players" / "serpentine_checkpoint.json"
    if not checkpoint.exists():
        print("GitHub publish skipped: scan completion checkpoint missing.")
        return False
    try:
        state = json.loads(checkpoint.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        print(f"GitHub publish skipped: unreadable scan checkpoint: {exc}")
        return False
    if state.get("phase") != "done" or (ROOT / state.get("session_relative", "")).resolve() != folder.resolve():
        print("GitHub publish skipped: this map capture session has not finished.")
        return False
    if len(captures) < 100:
        print(f"GitHub publish skipped: {len(captures)} captures; minimum 100 required to protect the full map.")
        return False
    if not captures or pending:
        print(f"GitHub publish skipped: {pending} screenshots have not been processed yet.")
        return False
    if rate < threshold:
        print(f"GitHub publish skipped: {failed}/{len(captures)} failed "
              f"({100-rate:.1f}%); maximum allowed failure rate is {100-threshold:.1f}%.")
        return False
    stamp = folder.name.removeprefix("session_")
    source = ROOT / "exports" / "players" / f"serpentine_players_{stamp}.csv"
    if not source.is_file():
        print(f"GitHub publish skipped: missing {source}")
        return False
    with source.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "username" not in reader.fieldnames:
            print("GitHub publish skipped: invalid player CSV.")
            return False
        rows = list(reader)
    if len(rows) < 7000:
        print(f"GitHub publish skipped: {len(rows)} player records; minimum 7000 required "
              "for a historical snapshot or live update.")
        return False
    metadata = {
        "session": folder.name,
        "completed": completed,
        "total": len(captures),
        "completion_percent": round(rate, 2),
        "player_count": len(rows),
        "published_at": datetime.now(timezone.utc).isoformat(),
    }
    # Use a temporary worktree so the scanner's dev branch is never merged.
    # Git uses the user's existing credentials; no token is stored in code.
    temp = Path(tempfile.mkdtemp(prefix="zroute-publish-"))
    worktree = temp / "checkout"
    attached = False
    try:
        subprocess.run(["git", "-C", str(ROOT), "fetch", "origin", branch], check=True)
        subprocess.run(["git", "-C", str(ROOT), "worktree", "add", "--detach",
                        str(worktree), f"origin/{branch}"], check=True)
        attached = True
        destination = worktree / "data" / "players.csv"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        (destination.parent / "map-players-meta.json").write_text(
            json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

        # Preserve each published scan as an immutable historical snapshot.
        history = destination.parent / "player_history"
        history.mkdir(parents=True, exist_ok=True)
        snapshot = history / f"{folder.name}.csv"
        if snapshot.exists():
            with snapshot.open("rb") as old, source.open("rb") as new:
                if old.read() != new.read():
                    print("GitHub publish skipped: historical snapshot already exists "
                          "with different content; refusing to overwrite history.")
                    return False
        else:
            shutil.copyfile(source, snapshot)

        # Guild counts are observations, not proof of membership departure.
        guild_counts = {}
        for row in rows:
            guild = (row.get("guild") or "").strip() or "(unknown)"
            guild_counts[guild] = guild_counts.get(guild, 0) + 1
        guild_summary = history / f"{folder.name}.guilds.json"
        summary = {"session": folder.name, "published_at": metadata["published_at"],
                   "guilds": [{"guild": tag, "observed_players": count}
                              for tag, count in sorted(guild_counts.items())]}
        if not guild_summary.exists():
            guild_summary.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        manifest_path = history / "index.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else []
            if not isinstance(manifest, list):
                raise ValueError("history index is not an array")
        except (OSError, ValueError) as exc:
            print(f"GitHub publish skipped: invalid historical index: {exc}")
            return False
        if not any(item.get("session") == folder.name for item in manifest):
            manifest.append({**metadata, "csv": f"data/player_history/{folder.name}.csv",
                             "guild_summary": f"data/player_history/{folder.name}.guilds.json"})
            manifest.sort(key=lambda item: item["session"])
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(worktree), "add",
                        "data/players.csv", "data/map-players-meta.json",
                        "data/player_history"], check=True)
        changed = subprocess.run(["git", "-C", str(worktree), "diff", "--cached",
                                  "--quiet"]).returncode
        if changed == 0:
            print("GitHub publish: data unchanged.")
            return True
        subprocess.run(["git", "-C", str(worktree), "commit", "-m",
                        f"Update map player scan ({rate:.1f}% analyzed)"], check=True)
        subprocess.run(["git", "-C", str(worktree), "push", "origin",
                        f"HEAD:refs/heads/{branch}"], check=True)
        print(f"GitHub publish successful: {len(rows)} players, {rate:.1f}% analyzed on {branch}.")
        return True
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"GitHub publish failed; local CSV preserved: {exc}")
        return False
    finally:
        if attached:
            subprocess.run(["git", "-C", str(ROOT), "worktree", "remove",
                            "--force", str(worktree)], check=False)
        shutil.rmtree(temp, ignore_errors=True)


def capture_ai_report(folder):
    captures = list(folder.glob("capture_col_*_view_*.png"))
    complete = sum(p.with_suffix(".players.json").exists() for p in captures)
    failed = sum(p.with_suffix(".failed.json").exists() and
                 not p.with_suffix(".players.json").exists() for p in captures)
    pending = len(captures) - complete - failed
    rate = 100 * complete / len(captures) if captures else 0
    print(f"AI report: {len(captures)} captured, {complete} completed, "
          f"{failed} failed, {pending} pending; success rate {rate:.1f}%.")


def scan_serpentine(cfg, max_swipes=150, columns=150, boundary_after=62, horizontal_after=160, resume=False, swipe_ms=100, settle=0.2, vertical_scale=1.0, horizontal_scale=1.0, profile=False, raw_capture=False):
    """Read-only bounded serpentine scan with one terminal horizontal edge."""
    if not 2 <= columns <= 150:
        raise ValueError("columns must be between 2 and 150")
    if not 1 <= max_swipes <= 500:
        raise ValueError("max_swipes must be between 1 and 500")
    if not 1 <= boundary_after <= max_swipes:
        raise ValueError("boundary_after must be between 1 and max_swipes")
    if not 0 <= horizontal_after <= 500:
        raise ValueError("horizontal_after must be between 0 and 500")
    if not 100 <= swipe_ms <= 1000 or not 0 <= settle <= 3:
        raise ValueError("Invalid swipe timing")
    if not 1.0 <= vertical_scale <= 1.2 or not 1.0 <= horizontal_scale <= 1.2:
        raise ValueError("Swipe scales must be between 1.0 and 1.2")
    if profile:
        cfg["_capture_metrics"] = {}
    # Grid coordinates are approximate scan-route positions, not game X/Y.
    # Checkpoint the CSV after every new username so interrupted scans retain data.
    export_folder = ROOT / "exports" / "players"
    export_folder.mkdir(parents=True, exist_ok=True)
    checkpoint_path = export_folder / "serpentine_checkpoint.json"
    settings = {"max_swipes": max_swipes, "columns": columns,
                "boundary_after": boundary_after, "horizontal_after": horizontal_after,
                "swipe_ms": swipe_ms, "settle": settle,
                "vertical_scale": vertical_scale, "horizontal_scale": horizontal_scale}
    if resume:
        if not checkpoint_path.exists():
            raise RuntimeError("No saved scan checkpoint exists.")
        state = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        previous_settings = dict(state["settings"])
        # Legacy checkpoints predate optional scaling; default values mean
        # identical swipe geometry, so old runs remain resumable.
        previous_settings.setdefault("vertical_scale", 1.0)
        previous_settings.setdefault("horizontal_scale", 1.0)
        # Verification timing can be raised without changing swipe geometry.
        geometry_keys = ("max_swipes", "columns", "swipe_ms", "settle",
                         "vertical_scale", "horizontal_scale")
        if any(previous_settings.get(key) != settings.get(key) for key in geometry_keys):
            raise RuntimeError("Scan geometry differs from checkpoint; use the original settings.")
        boundary_after = max(boundary_after, previous_settings.get("boundary_after", 0))
        horizontal_after = max(horizontal_after, previous_settings.get("horizontal_after", 0))
        print(f"Movement verification: vertical after {boundary_after} swipes per column; "
              f"horizontal after {horizontal_after} shifts.")
        if state.get("phase") == "connection_lost":
            raise RuntimeError("Game connection was lost. Reconnecting changes the map position; "
                               "automatic --continue is unsafe until repositioning is implemented. "
                               "Saved CSV and checkpoint remain intact.")
        if state.get("phase") not in ("view", "done"):
            raise RuntimeError("Last swipe/shift may have been interrupted. Position uncertain; "
                               "inspect BlueStacks and checkpoint before resuming.")
        if state["phase"] == "done":
            print("Scan already completed.")
            return
        export_path = ROOT / state["export_relative"]
        session_folder = ROOT / state["session_relative"]
        if not export_path.exists() or not session_folder.exists():
            raise RuntimeError("Session CSV or diagnostic folder is missing.")
        print("Resuming saved session at column", state["column"] + 1,
              "step", state["step"], "direction", state["direction"])
        print("Ensure the BlueStacks map has not been moved since interruption.")
    else:
        if checkpoint_path.exists():
            old = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            if old.get("phase") != "done":
                raise RuntimeError("An unfinished scan checkpoint exists. Use --continue to "
                                   "resume or archive/remove serpentine_checkpoint.json to start over.")
        export_stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
        export_path = export_folder / f"serpentine_players_{export_stamp}.csv"
        session_folder = ROOT / "screenshots" / f"session_{export_stamp}"
        session_folder.mkdir(parents=True, exist_ok=True)
        state = {"version": 1, "settings": settings, "column": 0, "step": 0,
                 "direction": "up", "phase": "view",
                 "export_relative": str(export_path.relative_to(ROOT)),
                 "session_relative": str(session_folder.relative_to(ROOT))}
    def save_state(column=None, step=None, phase=None):
        if column is not None:
            state["column"] = column
            state["direction"] = "up" if column % 2 == 0 else "down"
        if step is not None:
            state["step"] = step
        if phase is not None:
            state["phase"] = phase
        state["updated_at"] = datetime.now().astimezone().isoformat()
        tmp = checkpoint_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp.replace(checkpoint_path)
    cfg["_scan_session_folder"] = str(session_folder)
    print(f"Session diagnostics: {session_folder}")
    fields = ["username", "guild", "level", "row", "col", "view",
              "direction", "observed_at", "coordinate_type"]
    unique_players = {}
    if resume:
        with export_path.open(newline="", encoding="utf-8-sig") as handle:
            for player in csv.DictReader(handle):
                if player.get("username"):
                    unique_players[player["username"].casefold()] = player

    def save_players():
        temporary = export_path.with_suffix(".csv.tmp")
        with temporary.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(unique_players.values())
        temporary.replace(export_path)

    if not resume:
        save_players()
        save_state()
    # RAW capture is opt-in until its threaded scan path is validated.
    cfg["_raw_capture_enabled"] = raw_capture
    capture_queue = queue.Queue(maxsize=64) if raw_capture else queue.Queue()
    encoder_failure = threading.Event()
    encoder_last_error = []
    encoder_log = session_folder / "encoder_errors.log"
    runtime_log = session_folder / "scanner_runtime.log"
    fault_file = (session_folder / "python_faults.log").open("a", encoding="utf-8")
    faulthandler.enable(file=fault_file, all_threads=True)
    monitor_stop = threading.Event()
    progress = {"capture": time.monotonic(), "encode": time.monotonic(), "ai": time.monotonic(),
                "captured": 0, "encoded": 0, "analyzed": 0}
    def log_runtime(message):
        line = f"[{datetime.now(timezone.utc).isoformat()}] {message}"
        print(line, flush=True)
        with runtime_log.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    def memory_mb():
        if os.name != "nt":
            return "n/a"
        class PMC(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
        counters = PMC()
        counters.cb = ctypes.sizeof(counters)
        ok = ctypes.windll.psapi.GetProcessMemoryInfo(
            ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
        return f"{counters.WorkingSetSize / 1048576:.0f}MB" if ok else "unavailable"
    worker = None
    encoder = None
    def watchdog():
        while not monitor_stop.wait(10):
            now = time.monotonic()
            try:
                log_runtime("[HEALTH] "
                    f"column={state['column']+1}/{columns} view={state['step']} phase={state['phase']} "
                    f"RAW={capture_queue.qsize()}/64 AI={ai_queue.qsize()} "
                    f"encoder_alive={encoder.is_alive() if encoder else 'off'} "
                    f"AI_alive={worker.is_alive() if worker else False} RAM={memory_mb()} "
                    f"captured={progress['captured']} encoded={progress['encoded']} analyzed={progress['analyzed']} "
                    f"capture_idle={now-progress['capture']:.0f}s "
                    f"encode_idle={now-progress['encode']:.0f}s AI_idle={now-progress['ai']:.0f}s")
                if raw_capture and capture_queue.qsize() and now-progress["encode"] > 30:
                    log_runtime("[WATCHDOG WARNING] RAW images waiting, no encoding completion in 30s")
                if ai_queue.qsize() and now-progress["ai"] > 120:
                    log_runtime("[WATCHDOG WARNING] AI backlog with no completed result in 120s")
                if raw_capture and encoder and not encoder.is_alive():
                    encoder_failure.set()
                    log_runtime("[WATCHDOG ERROR] Encoder thread is not alive")
                if worker and not worker.is_alive():
                    log_runtime("[WATCHDOG ERROR] AI thread is not alive")
            except Exception:
                print("[WATCHDOG ERROR] " + traceback.format_exc(), flush=True)
    monitor = threading.Thread(target=watchdog, daemon=True, name="scanner-watchdog")
    monitor.start()
    def report_encoder_error(message):
        detail = f"[{datetime.now(timezone.utc).isoformat()}] {message}\n"
        encoder_last_error.append(detail)
        print(f"[ENCODER ERROR] {detail}", flush=True)
        with encoder_log.open("a", encoding="utf-8") as log:
            log.write(detail)
    def enqueue_raw(item):
        if isinstance(item, tuple):
            path, image, meta = item
            raw_path = path.with_suffix(".raw.npy")
            temp = path.with_suffix(".raw.tmp")
            # Persist the screenshot before navigation can advance.
            with temp.open("wb") as handle:
                np.save(handle, image, allow_pickle=False)
                handle.flush()
                os.fsync(handle.fileno())
            temp.replace(raw_path)
            metadata_path = path.with_suffix(".meta.json")
            metadata_temp = path.with_suffix(".meta.json.tmp")
            metadata_temp.write_text(json.dumps(meta), encoding="utf-8")
            metadata_temp.replace(metadata_path)
            item = path
            progress["capture"] = time.monotonic()
            progress["captured"] += 1
        while True:
            if encoder_failure.is_set() or (encoder is not None and not encoder.is_alive()):
                raise RuntimeError(f"RAW encoder worker stopped; see {encoder_log}")
            try:
                capture_queue.put(item, timeout=5)
                return
            except queue.Full:
                print(f"[ENCODER WAIT] RAW queue full ({capture_queue.qsize()}/64); encoder_alive={encoder.is_alive() if encoder else False}; AI_pending={ai_queue.qsize()}", flush=True)
    ai_queue = queue.Queue()
    encoding_errors = []
    def encode_captures():
        try:
            _encode_captures_loop()
        except BaseException:
            encoder_failure.set()
            report_encoder_error("FATAL encoder thread exception:\n" + traceback.format_exc())
    def _encode_captures_loop():
        while True:
            item = capture_queue.get()
            try:
                if item is None:
                    return
                path = item
                raw_path = path.with_suffix(".raw.npy")
                temporary = path.with_suffix(".png.tmp")
                try:
                    with raw_path.open("rb") as handle:
                        image = np.load(handle, allow_pickle=False)
                    ok, encoded = cv2.imencode(".png", image)
                    if not ok:
                        raise RuntimeError("PNG encoding failed")
                    temporary.write_bytes(encoded.tobytes())
                    temporary.replace(path)
                    ai_queue.put(path)
                    raw_path.unlink(missing_ok=True)
                    progress["encode"] = time.monotonic()
                    progress["encoded"] += 1
                except Exception as exc:
                    encoding_errors.append(str(exc))
                    report_encoder_error(f"Encoding FAILED for {path.name}:\n{traceback.format_exc()}")
                    temporary.unlink(missing_ok=True)
            finally:
                capture_queue.task_done()
    cfg["_enqueue_raw"] = enqueue_raw if raw_capture else None
    if raw_capture:
        encoder = threading.Thread(target=encode_captures, daemon=True, name="png-encoder")
        encoder.start()
    def analyze_captures():
        while True:
            path = ai_queue.get()
            try:
                if path is None:
                    return
                try:
                    process_capture_ai(cfg, path, unique_players, save_players)
                except Exception:
                    log_runtime("[AI ERROR] " + traceback.format_exc())
                finally:
                    progress["ai"] = time.monotonic()
                    progress["analyzed"] += 1
            finally:
                ai_queue.task_done()
    worker = threading.Thread(target=analyze_captures, daemon=True, name="ollama-worker")
    worker.start()
    # Requeue durable RAW frames from this session, without moving the map.
    if raw_capture:
        recovered = 0
        for raw_path in sorted(session_folder.glob("capture_col_*_view_*.raw.npy")):
            path = Path(str(raw_path)[:-8] + ".png")
            if path.exists() and path.with_suffix(".meta.json").exists():
                raw_path.unlink(missing_ok=True)
                continue
            if not path.with_suffix(".meta.json").exists():
                log_runtime(f"[RECOVERY WARNING] Metadata missing for {raw_path.name}")
                continue
            enqueue_raw(path)
            recovered += 1
        log_runtime(f"[RECOVERY] Requeued {recovered} durable RAW captures")
    # On resume, retry a previously failed screenshot at most once across
    # all subsequent resumes. New/pending screenshots still get their first pass.
    queued_retries = 0
    skipped_retries = 0
    for path in sorted(session_folder.glob("capture_col_*_view_*.png")):
        if path.with_suffix(".players.json").exists():
            continue
        failed_path = path.with_suffix(".failed.json")
        retry_marker = path.with_suffix(".resume-retried.json")
        if failed_path.exists():
            if retry_marker.exists():
                skipped_retries += 1
                continue
            retry_marker.write_text(json.dumps({
                "retried_at": datetime.now(timezone.utc).isoformat(),
                "reason": "one allowed resume retry after initial failure",
            }), encoding="utf-8")
            queued_retries += 1
        ai_queue.put(path)
    print(f"Resume AI queue: {queued_retries} failed screenshots queued for their one retry; "
          f"{skipped_retries} previously retried screenshots skipped.")
    successful_horizontal_shifts = 0
    termination = "column limit reached"
    try:
        for column in range(state["column"], columns):
            direction = "up" if column % 2 == 0 else "down"
            initial_step = state["step"] if column == state["column"] else 0
            save_state(column=column, step=initial_step, phase="view")
            cfg["_scan_grid_context"] = {"column": column + 1}
            print(f"=== Column {column + 1}/{columns}: {direction} ===")
            def record_player(player, step):
                name = str(player.get("username") or "").strip()
                if not valid_scanned_username(name):
                    return
                key = name.casefold()
                if key in unique_players:
                    return
                unique_players[key] = {
                    "username": name,
                    "guild": str(player.get("guild") or ""),
                    "level": player.get("level") if player.get("level") is not None else "",
                    "row": step + 1 if direction == "up" else max_swipes - step + 1,
                    "col": column + 1,
                    "view": step,
                    "direction": direction,
                    "observed_at": datetime.now().astimezone().isoformat(),
                    "coordinate_type": "approximate swipe grid",
                }
                save_players()
                print(f"CSV checkpoint: {len(unique_players)} unique usernames -> {export_path}")

            # Fixed 60-swipe column height for serpentine navigation.
            column_swipe_limit = min(max_swipes, 60)
            if initial_step > column_swipe_limit:
                raise RuntimeError(
                    f"Checkpoint step {initial_step} exceeds fixed column limit "
                    f"{column_swipe_limit}. Inspect BlueStacks before resuming.")
            reason, vertical_swipes = scan_column(cfg, max_swipes=column_swipe_limit, direction=direction,
                                                  verify_after=boundary_after,
                                                  on_player=record_player,
                                                  start_step=initial_step, swipe_ms=swipe_ms,
                                                  settle=settle, capture_queue=capture_queue,
                                                  vertical_scale=vertical_scale,
                                                  on_progress=lambda step, phase: save_state(
                                                      column=column, step=step, phase=phase))
            if reason == "swipe limit reached" and vertical_swipes == column_swipe_limit:
                print(f"Column {column + 1}: reached {column_swipe_limit} vertical swipes; "
                      "turning horizontally without vertical movement verification.")
                reason = "fixed column limit reached"
            # A short column may be real, but never turn early in a large-map run.
            # This prevents an isolated stationary/low-texture frame from triggering
            # a horizontal transition before the configured search horizon.
            # Each column starts a fresh vertical boundary-check horizon.
            if column == columns - 1:
                break
            if reason == "stationary map / possible boundary" and vertical_swipes < boundary_after:
                termination = "stationary before boundary-check horizon"
                print(f"Stopped after {vertical_swipes} swipes; horizontal transitions "
                      f"require at least {boundary_after}. No turn attempted.")
                break
            if reason not in ("stationary map / possible boundary", "fixed column limit reached"):
                termination = "vertical endpoint not verified"
                print("No verified stationary endpoint; horizontal transition cancelled.")
                break
            save_state(column=column, step=vertical_swipes, phase="shift_pending")
            before = screenshot(cfg)
            ensure_game_connected(cfg, before, lambda step, phase: save_state(phase=phase))
            x1, y1, x2, y2 = middle_scan_rectangle(before, cfg)
            # Horizontal gesture stays inside the established safe map rectangle.
            cy = (y1 + y2) // 2
            sx = int(x1 + (x2 - x1) * .76)
            ex = int(x1 + (x2 - x1) * .24)
            sx, ex = scaled_swipe(sx, ex, horizontal_scale, x1, x2)
            print(f"Attempting horizontal shift {column + 1}...")
            # Faster horizontal transitions: 250 ms gesture and 0.5 s settle.
            adb(cfg, "shell", "input", "swipe", str(sx), str(cy),
                str(ex), str(cy), "250")
            time.sleep(0.5)
            if column + 1 <= horizontal_after:
                print(f"Horizontal verification deferred until shift {horizontal_after + 1}. "
                      "Reversing vertical direction.")
                save_state(column=column + 1, step=0, phase="view")
                continue
            after = screenshot(cfg)
            ensure_game_connected(cfg, after, lambda step, phase: save_state(phase=phase))
            first = cv2.cvtColor(before[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
            second = cv2.cvtColor(after[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
            orb = cv2.ORB_create(nfeatures=1400)
            k1, d1 = orb.detectAndCompute(first, None)
            k2, d2 = orb.detectAndCompute(second, None)
            if d1 is None or d2 is None:
                print("Horizontal shift unverified: missing landmarks. Stopping.")
                break
            pairs = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(d1, d2, k=2)
            good = [a for pair in pairs if len(pair) == 2
                    for a, b in [pair] if a.distance < .72 * b.distance]
            if len(good) < 30:
                print("Horizontal shift unverified: too few matches. Stopping.")
                break
            src = np.float32([k1[m.queryIdx].pt for m in good])
            dst = np.float32([k2[m.trainIdx].pt for m in good])
            # Match groups may contain a dominant stationary overlay plus a moving
            # map. Inspect the displacement vectors, not only the dominant RANSAC fit.
            offsets = dst - src
            moving = (offsets[:, 0] < -25) & (offsets[:, 0] >= -950) & (np.abs(offsets[:, 1]) <= 80)
            moving_offsets = offsets[moving]
            accepted = False
            dx = dy = 0.0
            if len(moving_offsets) >= 12:
                # Find a coherent horizontal displacement cluster, allowing a few
                # mismatches and avoiding accidental UI-animation matches.
                best = np.zeros(len(moving_offsets), dtype=bool)
                for candidate in moving_offsets:
                    cluster = np.linalg.norm(moving_offsets - candidate, axis=1) <= 12
                    if cluster.sum() > best.sum():
                        best = cluster
                if best.sum() >= 12:
                    consensus = moving_offsets[best]
                    median = np.median(consensus, axis=0)
                    residual = np.linalg.norm(consensus - median, axis=1)
                    dx, dy = float(median[0]), float(median[1])
                    accepted = (float(np.median(residual)) <= 6
                                and best.sum() >= max(12, int(len(good) * .04)))
                    print(f"Horizontal moving consensus: {int(best.sum())}/{len(good)} "
                          f"matches, dx={dx:.1f}, dy={dy:.1f}, "
                          f"median residual={np.median(residual):.1f}px.")
            if not accepted:
                transform, mask = cv2.estimateAffinePartial2D(
                    src, dst, method=cv2.RANSAC, ransacReprojThreshold=4)
                inliers = int(mask.sum()) if mask is not None else 0
                if transform is not None and mask is not None and inliers >= 30:
                    dx, dy = float(transform[0, 2]), float(transform[1, 2])
                    if (abs(dx) < 10 and abs(dy) < 10
                            and inliers / len(good) >= .8
                            and len(moving_offsets) < 12):
                        termination = ("probable far horizontal boundary"
                                       if successful_horizontal_shifts else
                                       "stationary on first horizontal attempt")
                        print(f"Stationary horizontal view: {inliers}/{len(good)} "
                              f"inliers, dx={dx:.1f}, dy={dy:.1f}.")
                        break
                termination = "horizontal movement unverified"
                print(f"Horizontal movement unverified; {len(moving_offsets)} "
                      f"plausible moving matches among {len(good)}. Stopping.")
                break
            print(f"Horizontal shift accepted: dx={dx:.1f}, dy={dy:.1f}")
            successful_horizontal_shifts += 1
            print("Horizontal shift verified. Reversing vertical direction.")
            save_state(column=column + 1, step=0, phase="view")
    finally:
        if profile:
            print_capture_metrics(cfg)
        print("Navigation stopped; waiting for queued AI analysis to finish...")
        if raw_capture:
            if encoder.is_alive():
                enqueue_raw(None)
                capture_queue.join()
                encoder.join()
            else:
                print(f"[ENCODER ERROR] Worker already stopped; pending RAW frames={capture_queue.qsize()}; log={encoder_log}", flush=True)
        ai_queue.put(None)
        ai_queue.join()
        worker.join()
        monitor_stop.set()
        monitor.join(timeout=2)
        cfg["_raw_capture_enabled"] = False
        cfg["_enqueue_raw"] = None
        if encoding_errors:
            print(f"WARNING: {len(encoding_errors)} screenshot encoding failures; review session before resuming.")
        capture_ai_report(session_folder)
        print(f"Navigation checkpoint: {checkpoint_path} (column {state['column'] + 1}, "
              f"step {state['step']}, {state['direction']}, phase={state['phase']})")
        # Recover only this session's screenshots, retaining their original grid
        # coordinates. Never move the map during offline recovery.
        try:
            pending = sorted(session_folder.glob("column_unanalyzed_*.png"))
            print(f"End-of-session recovery: {len(pending)} failed screenshots.")
            for index, path in enumerate(pending, 1):
                result_path = path.with_suffix(".recovered.json")
                meta_path = path.with_suffix(".meta.json")
                if result_path.exists() or not meta_path.exists():
                    continue
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    image = cv2.imread(str(path))
                    if image is None:
                        print(f"Recovery {index}: unreadable screenshot {path.name}")
                        continue
                    try:
                        players = debug_ollama(cfg, image=image)
                    except (RuntimeError, OSError, TimeoutError, ValueError):
                        players = analyze_split_fallback(cfg, image)
                    result_path.write_text(json.dumps({
                        "source_screenshot": path.name,
                        "grid": meta,
                        "reprocessed_at": datetime.now(timezone.utc).isoformat(),
                        "players": players,
                        "verified": False,
                    }, indent=2, ensure_ascii=False), encoding="utf-8")
                    recovered_count = 0
                    for player in players:
                        if not isinstance(player, dict) or is_ignored_commander(player):
                            continue
                        name = player.get("username")
                        if not valid_scanned_username(name):
                            print(f"Ignoring invalid recovered username: {name!r}")
                            continue
                        key = name.strip().casefold()
                        if key in unique_players:
                            continue
                        unique_players[key] = {
                            "username": name.strip(),
                            "guild": str(player.get("guild") or ""),
                            "level": player.get("level") if player.get("level") is not None else "",
                            "row": meta["row"],
                            "col": meta["column"],
                            "view": meta["view"],
                            "direction": meta["direction"],
                            "observed_at": meta["captured_at"],
                            "coordinate_type": "approximate swipe grid (recovered)",
                        }
                        save_players()
                        recovered_count += 1
                    print(f"Recovery {index}/{len(pending)}: {recovered_count} new players from {path.name}")
                except (RuntimeError, OSError, TimeoutError, ValueError, KeyError, TypeError) as exc:
                    print(f"Recovery failed for {path.name}: {exc}")
        except Exception as exc:
            print(f"Recovery pass interrupted: {exc}")
        finally:
            save_players()
            print(f"Player grid CSV saved: {export_path} ({len(unique_players)} unique usernames).")
            cfg.pop("_scan_grid_context", None)
            cfg.pop("_scan_session_folder", None)
    if termination == "column limit reached" and column == columns - 1:
        save_state(phase="done")
        retry_failed_after_scan(cfg, session_folder, unique_players, save_players)
        print("Publishing disabled for automatic scans; use publish-scan explicitly after reviewing results.")
    print(f"Serpentine diagnostic finished: {successful_horizontal_shifts} verified "
          f"horizontal shifts; reason: {termination}.")
    print("No database writes or base clicks.")


def reprocess_failed(cfg, limit=None, all_sessions=False):
    """Offline retry of latest session by default; no ADB or map movement."""
    folders = sorted((p for p in (ROOT / "screenshots").glob("session_*") if p.is_dir()), reverse=True)
    if not all_sessions:
        folders = folders[:1]
    if not folders:
        print("No screenshot session folders found.")
        return
    print("Offline AI session(s): " + ", ".join(p.name for p in folders))
    pending = [p for folder in folders
               for p in sorted(folder.glob("capture_col_*_view_*.png"))
               if not p.with_suffix(".players.json").exists()]
    if limit is not None:
        pending = pending[:limit]
    print(f"Offline AI retry: {len(pending)} pending/failed captures.")
    for path in pending:
        # Session timestamp is embedded in both directory and CSV filename.
        stamp = path.parent.name.removeprefix("session_")
        csv_path = ROOT / "exports" / "players" / f"serpentine_players_{stamp}.csv"
        if not csv_path.exists():
            print(f"Missing session CSV for {path}; leaving screenshot pending.")
            continue
        fields = ["username", "guild", "level", "row", "col", "view",
                  "direction", "observed_at", "coordinate_type"]
        with csv_path.open(newline="", encoding="utf-8-sig") as handle:
            unique = {row["username"].casefold(): row for row in csv.DictReader(handle)
                      if row.get("username")}
        def save():
            tmp = csv_path.with_suffix(".csv.tmp")
            with tmp.open("w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(unique.values())
            tmp.replace(csv_path)
        cfg["_scan_session_folder"] = str(path.parent)
        try:
            process_capture_ai(cfg, path, unique, save)
        finally:
            cfg.pop("_scan_session_folder", None)
    for folder in folders:
        capture_ai_report(folder)
    if not all_sessions and folders:
        print("Automatic publishing disabled; review results and use publish-scan explicitly.")
    print("Offline retry finished; no map movement or database writes.")


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("test", "probe", "scan", "guilds", "export", "debug-nameplates", "debug-ollama", "calibrate-movement", "benchmark-capture", "benchmark-screenshot", "calibrate-capture-ai", "scan-column", "scan-serpentine", "reprocess-failed", "publish-scan"):
        commands.add_parser(name)
    commands.choices["benchmark-screenshot"].add_argument("--samples", type=int, default=10)
    commands.choices["calibrate-capture-ai"].add_argument("--samples", type=int, default=3)
    commands.choices["benchmark-capture"].add_argument("--swipes", type=int, default=110)
    commands.choices["benchmark-capture"].add_argument("--settle", type=float, default=0.2)
    commands.choices["benchmark-capture"].add_argument("--swipe-ms", type=int, default=250)
    commands.choices["scan-column"].add_argument(
        "--max-swipes", type=int, default=5,
        help="Maximum upward swipes (1-500; default 5). Read-only.")
    commands.choices["scan-serpentine"].add_argument("--vertical-scale", type=float, default=1.0)
    commands.choices["scan-serpentine"].add_argument("--horizontal-scale", type=float, default=1.0)
    commands.choices["scan-serpentine"].add_argument("--profile", action="store_true")
    commands.choices["scan-serpentine"].add_argument("--raw-capture", action="store_true", help="Capture RAW framebuffer and encode PNG on a background thread.")
    commands.choices["scan-serpentine"].add_argument("--swipe-ms", type=int, default=100)
    commands.choices["scan-serpentine"].add_argument("--settle", type=float, default=0.2)
    commands.choices["scan-serpentine"].add_argument(
        "--continue", dest="resume", action="store_true",
        help="Resume the saved scan session and CSV from its checkpoint.")
    commands.choices["scan-serpentine"].add_argument(
        "--max-swipes", type=int, default=150,
        help="Maximum vertical swipes per column (1-500; default 150).")
    commands.choices["scan-serpentine"].add_argument(
        "--boundary-after", type=int, default=62,
        help="Skip vertical movement checks for this many swipes per column (default 62).")
    commands.choices["scan-serpentine"].add_argument(
        "--columns", type=int, default=150,
        help="Maximum columns to scan (2-150; default and hard maximum 150; automatically stops after column 150)."
    )
    commands.choices["scan-serpentine"].add_argument(
        "--horizontal-after", type=int, default=160,
        help="Skip verification of the first N horizontal shifts (default 160).")
    commands.choices["reprocess-failed"].add_argument(
        "--limit", type=int, default=None,
        help="Maximum number of pending/failed screenshots to retry.")
    commands.choices["reprocess-failed"].add_argument(
        "--all-sessions", action="store_true",
        help="Retry all saved sessions instead of only the latest session.")
    commands.choices["publish-scan"].add_argument("--threshold", type=float, default=90.0)
    query = commands.add_parser("search")
    query.add_argument("username")
    args = parser.parse_args()
    if args.command == "publish-scan":
        folders = sorted((p for p in (ROOT / "screenshots").glob("session_*") if p.is_dir()), reverse=True)
        if not folders:
            parser.error("No saved screenshot sessions.")
        if not 0 < args.threshold <= 100:
            parser.error("--threshold must be between 0 and 100")
        publish_scan_csv(folders[0], threshold=args.threshold)
    elif args.command in ("test", "probe", "scan", "debug-nameplates", "debug-ollama", "calibrate-movement", "benchmark-capture", "benchmark-screenshot", "calibrate-capture-ai", "scan-column", "scan-serpentine", "reprocess-failed"):
        cfg = load_config()
        if args.command == "reprocess-failed":
            if args.limit is not None and args.limit < 1:
                parser.error("--limit must be at least 1")
            reprocess_failed(cfg, limit=args.limit, all_sessions=args.all_sessions)
        elif args.command == "scan-serpentine":
            connect(cfg)
            scan_serpentine(cfg, max_swipes=args.max_swipes, columns=args.columns,
                            boundary_after=args.boundary_after,
                            horizontal_after=args.horizontal_after,
                            vertical_scale=args.vertical_scale,
                            horizontal_scale=args.horizontal_scale, profile=args.profile, resume=args.resume,
                            swipe_ms=args.swipe_ms, settle=args.settle, raw_capture=args.raw_capture)
        elif args.command == "scan-column":
            connect(cfg)
            scan_column(cfg, max_swipes=args.max_swipes)
        elif args.command == "calibrate-capture-ai":
            connect(cfg)
            calibrate_capture_ai(cfg, samples=args.samples)
        elif args.command == "benchmark-screenshot":
            connect(cfg)
            benchmark_screenshot(cfg, samples=args.samples)
        elif args.command == "benchmark-capture":
            connect(cfg)
            benchmark_capture(cfg, swipes=args.swipes, settle=args.settle, swipe_ms=args.swipe_ms)
        elif args.command == "calibrate-movement":
            connect(cfg)
            calibrate_movement(cfg)
        elif args.command == "debug-ollama":
            connect(cfg)
            debug_ollama(cfg)
        elif args.command == "test":
            test(cfg)
        elif args.command == "debug-nameplates":
            connect(cfg)
            debug_nameplates(cfg)
        else:
            raise SystemExit(
                "Not calibrated: base-click and map navigation are intentionally "
                "disabled until coordinate semantics are verified. Run test first.")
        return
    db = setup_db()
    if args.command == "search":
        rows = db.execute("""SELECT p.server,p.username,g.tag,p.x,p.y,p.last_seen
          FROM players p LEFT JOIN guilds g ON p.guild_id=g.id
          WHERE p.username LIKE ? ORDER BY p.last_seen DESC""",
                          ("%" + args.username + "%",)).fetchall()
    elif args.command == "guilds":
        rows = db.execute("""SELECT g.server,g.tag,COUNT(p.id) FROM guilds g
          LEFT JOIN players p ON p.guild_id=g.id GROUP BY g.id
          ORDER BY COUNT(p.id) DESC""").fetchall()
    else:
        rows = db.execute("""SELECT p.server,p.username,g.tag,p.x,p.y,p.last_seen
          FROM players p LEFT JOIN guilds g ON p.guild_id=g.id""").fetchall()
        with (ROOT / "players.csv").open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["server","username","guild","x","y","last_seen"])
            writer.writerows(rows)
        print("Exported", len(rows), "players")
        return
    for row in rows:
        print(*row, sep=" | ")


if __name__ == "__main__":
    main()
