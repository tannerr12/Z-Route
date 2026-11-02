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



GUILD_RE = re.compile(r"^\\[([A-Za-z0-9]{2,8})\\]$")
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


def debug_nameplates(cfg):
    """Write an annotated image; no base clicks or database writes."""
    image = screenshot(cfg)
    output = image.copy()
    masks = ui_mask_rectangles(image, cfg)
    candidates = nameplate_candidates(image, cfg.get("ocr", {}).get("bottom_exclusion_ratio", 0.09), cfg.get("ocr", {}).get("top_exclusion_ratio", 0.08), masks)
    groups = grouped_player_candidates(candidates)
    for group in groups:
        x1, y1, x2, y2 = group["box"]
        cv2.rectangle(output, (x1, y1), (x2, y2), (0, 255, 0), 2)
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
    for group in groups:
        print("  [{}] {} confidence={} box={}".format(
            group["guild"], group["username"], group["confidence"], group["box"]))
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
