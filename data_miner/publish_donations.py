"""Publish locally mined donations into the GitHub Pages guild CSV directory.

This prepares repository files; git commit/push is a separate step.
"""
import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data_miner" / "output" / "donations.csv"
DEST = ROOT / "data" / "donations"
FIELDS = ["week_start", "rank", "username", "role", "points", "captured_at", "evidence"]


def publish_guild(guild):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,50}", guild):
        raise ValueError("Guild must be 1-50 letters, numbers, hyphens or underscores")
    if not SOURCE.is_file():
        raise FileNotFoundError(SOURCE)
    folder = DEST / guild
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "donations.csv"
    with SOURCE.open(newline="", encoding="utf-8") as f:
        source = list(csv.DictReader(f))
    if not source:
        raise ValueError("No mined donations to publish")
    combined = {}
    if target.exists():
        with target.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                combined[(r["week_start"], r["rank"])] = r
    for r in source:
        combined[(r["week_start"], r["rank"])] = {k: r.get(k, "") for k in FIELDS}
    with target.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(sorted(combined.values(), key=lambda r: (r["week_start"], int(r["rank"]))))
    manifest_path = DEST / "guilds.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"guilds": []}
    guilds = manifest.get("guilds", [])
    if not any(g.get("folder") == guild for g in guilds):
        guilds.append({"name": guild, "folder": guild})
    manifest_path.write_text(json.dumps({"guilds": sorted(guilds, key=lambda g: g["name"].casefold())}, indent=2)+"\n", encoding="utf-8")
    return target
