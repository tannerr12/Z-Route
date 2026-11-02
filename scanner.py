"""Z Route BlueStacks scanner: initial calibration and database prototype."""
import argparse
import csv
import json
import re
import sqlite3
import subprocess
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
    return subprocess.run([exe, "-s", serial, *args],
                          check=True, capture_output=True, timeout=30).stdout


def screenshot(cfg):
    raw = adb(cfg, "exec-out", "screencap", "-p")
    image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError("Unable to decode screenshot")
    return image


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
    top = int(height * max(0.15625, cfg.get("ocr", {}).get("top_exclusion_ratio", 0.08)))
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
    top = int(height * max(0.15625, cfg.get("ocr", {}).get("top_exclusion_ratio", .08)))
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
        raw = max(readings, key=lambda value: len(value))
        match = re.match(r"^\[([A-Za-z0-9]{2,8})\]\s*(.+)$", raw)
        guild = match.group(1) if match else None
        username = (match.group(2) if match else raw).strip(" |[]")
        if not (3 <= len(username) <= 30) or not re.search(r"[A-Za-z]", username):
            continue
        if any(phrase in raw.casefold() for phrase in IGNORE_PHRASES):
            continue
        proposals.append({"guild": guild, "username": username,
                          "box": (x1, y1, x2, y2),
                          "confidence": 0.0, "source": "dark-strip",
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


def combined_player_candidates(image, tokens, cfg):
    """Fuse guild-anchored OCR with line OCR; suppress weak untagged noise.

    Candidate-only diagnostics; no player database writes.
    """
    anchored = grouped_player_candidates(tokens)
    lines = line_player_candidates(image, tokens, cfg)
    dark_strips = dark_strip_candidates(image, cfg)
    height, width = image.shape[:2]
    result = []
    for item in anchored:
        result.append({**item, "source": "guild-anchor", "verified": False})
    for item in lines:
        x1, y1, x2, y2 = item["box"]
        w, h = x2-x1, y2-y1
        # Single tiny fragments and overly wide announcements aren't nameplates.
        if not (42 <= w <= min(250, width * .30) and 10 <= h <= 34):
            continue
        if not item["guild"]:
            # Untagged names require stronger visual evidence, pending popup verification.
            if not (55 <= w <= 190 and 12 <= h <= 28 and
                    len(item["username"]) >= 4 and
                    re.fullmatch(r"[\\w .~'-]{4,30}", item["username"])):
                continue
        result.append({**item, "source": "line-ocr", "verified": False})
    result.extend(dark_strips)
    # Deduplicate by spatial overlap and name similarity; prefer anchored guild tags.
    def priority(item):
        return (item["source"] == "guild-anchor", bool(item["guild"]),
                item["confidence"])
    merged = []
    for item in sorted(result, key=priority, reverse=True):
        ax1, ay1, ax2, ay2 = item["box"]
        if any(
            abs((ax1+ax2)/2 - (b["box"][0]+b["box"][2])/2) < 40
            and abs((ay1+ay2)/2 - (b["box"][1]+b["box"][3])/2) < 16
            for b in merged
        ):
            continue
        merged.append(item)
    merged = [item for item in merged if item["box"][1] >= int(height * .15625)]
    for item in merged:
        item["level"] = read_base_level(image, item["box"])
        item["level_supported"] = item["level"] is not None
    return sorted(merged, key=lambda g: (g["box"][1], g["box"][0]))


def debug_nameplates(cfg):
    """Write an annotated image; no base clicks or database writes."""
    image = screenshot(cfg)
    output = image.copy()
    masks = ui_mask_rectangles(image, cfg)
    candidates = nameplate_candidates(image, cfg.get("ocr", {}).get("bottom_exclusion_ratio", 0.09), cfg.get("ocr", {}).get("top_exclusion_ratio", 0.08), masks)
    groups = combined_player_candidates(image, candidates, cfg)
    for group in groups:
        x1, y1, x2, y2 = group["box"]
        color = (255, 0, 255) if group.get("source") == "dark-strip" else ((0, 255, 0) if group["guild"] else (255, 165, 0))
        cv2.rectangle(output, (x1, y1), (x2, y2), color, 2)
        if group["level"] is not None:
            cv2.putText(output, "Lv." + str(group["level"]), (x1, min(image.shape[0]-4, y2+34)),
                        cv2.FONT_HERSHEY_SIMPLEX, .55, (0, 255, 0), 2)
    for x1, y1, x2, y2 in masks:
        cv2.rectangle(output, (x1, y1), (x2, y2), (0, 0, 255), 2)
    cutoff = int(image.shape[0] * (1 - cfg.get("ocr", {}).get("bottom_exclusion_ratio", 0.09)))
    cv2.line(output, (0, cutoff), (image.shape[1], cutoff), (0, 0, 255), 2)
    top = int(image.shape[0] * cfg.get("ocr", {}).get("top_exclusion_ratio", 0.08))
    cv2.line(output, (0, top), (image.shape[1], top), (0, 0, 255), 2)
    for x, y, w, h, token, confidence in candidates:
        cv2.rectangle(output, (x, y), (x+w, y+h), (0, 255, 255), 1)
    folder = ROOT / "screenshots"
    folder.mkdir(exist_ok=True)
    path = folder / "nameplate_candidates.png"
    cv2.imwrite(str(path), output)
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
    folder = ROOT / "screenshots"
    folder.mkdir(exist_ok=True)
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


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("test", "probe", "scan", "guilds", "export", "debug-nameplates"):
        commands.add_parser(name)
    query = commands.add_parser("search")
    query.add_argument("username")
    args = parser.parse_args()
    if args.command in ("test", "probe", "scan", "debug-nameplates"):
        cfg = load_config()
        if args.command == "test":
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
