#!/usr/bin/env python3
"""Append-only player identity and observed-name history for Z-Route.

Uses (server, player_id) as the stable identity. Never treats names as keys.
Imports saved scan CSV snapshots into a private SQLite database, preserving
older names even when a later scan overwrites a players.csv.

  python network_scan/player_history.py sync
  python network_scan/player_history.py show --id 125:137434890365
  python network_scan/player_history.py export

All timestamps describe *when a snapshot was saved*, or the time a scan's
checkpoint says it finished; they are NOT exact name-change times.
No ADB/game-server calls; no public publishing.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DB = Path('network_scans/player_history.sqlite3')
DEFAULT_ROOT = Path('network_scans')
FIELDS = ('server', 'player_id', 'username', 'alliance_tag', 'alliance_name',
          'base_level', 'x', 'y', 'capture', 'time_s')


def connection(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.executescript("""
    PRAGMA foreign_keys=ON;
    CREATE TABLE IF NOT EXISTS snapshots (
       id INTEGER PRIMARY KEY,
       source TEXT NOT NULL,
       content_sha TEXT NOT NULL,
       saved_at TEXT NOT NULL,
       timestamp_basis TEXT NOT NULL,
       imported_at TEXT NOT NULL,
       row_count INTEGER NOT NULL DEFAULT 0,
       UNIQUE(source, content_sha)
    );
    CREATE TABLE IF NOT EXISTS observations (
       snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
       server TEXT NOT NULL,
       player_id TEXT NOT NULL,
       username TEXT NOT NULL,
       alliance_tag TEXT,
       alliance_name TEXT,
       base_level TEXT,
       x TEXT,
       y TEXT,
       capture TEXT,
       observed_at TEXT NOT NULL,
       timestamp_basis TEXT NOT NULL,
       PRIMARY KEY(snapshot_id,server,player_id)
    );
    CREATE INDEX IF NOT EXISTS player_history_lookup
       ON observations(server,player_id,observed_at,snapshot_id);
    CREATE INDEX IF NOT EXISTS player_history_name
       ON observations(server,username);
    """)
    return db


def discovery(root):
    """Distinct raw roster sources. Combined CSV is only a fallback."""
    paths = list((root / 'live').glob('*/players.csv'))
    paths += [p for p in (root / 'full_map' / 'players.csv',) if p.is_file()]
    if not paths and (root / 'combined_players.csv').is_file():
        paths = [root / 'combined_players.csv']
    return sorted(set(paths))


def iso_mtime(path):
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()


def checkpoint_times(csv_path):
    if csv_path.parent.name != 'full_map':
        return {}
    checkpoint = csv_path.parent / 'checkpoint.json'
    if not checkpoint.is_file():
        return {}
    try:
        entries = json.loads(checkpoint.read_text(encoding='utf-8')).get('entries', [])
    except (OSError, ValueError):
        return {}
    results = {}
    for entry in entries:
        name = Path(entry.get('capture') or '').name
        when = entry.get('updated_at')
        if name and when:
            results[name] = str(when)
    return results


def import_csv(db, csv_path, root=DEFAULT_ROOT):
    csv_path = Path(csv_path)
    if not csv_path.is_file():
        raise ValueError('Missing source file: ' + str(csv_path))
    raw = csv_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    try:
        source = csv_path.resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        source = str(csv_path.resolve())
    if db.execute('SELECT 1 FROM snapshots WHERE source=? AND content_sha=?',
                  (source, digest)).fetchone():
        return 0, 0
    saved_at = iso_mtime(csv_path)
    # File mtime is a proxy for when this snapshot was written. If an
    # individual full_map capture matches its checkpoint, prefer the
    # more specific per-click completion timestamp.
    time_map = checkpoint_times(csv_path)
    with csv_path.open(newline='', encoding='utf-8-sig') as stream:
        reader = csv.DictReader(stream)
        if not {'server', 'player_id', 'username'}.issubset(reader.fieldnames or []):
            raise ValueError('Missing player identity columns in '+str(csv_path))
        rows = {}
        for row in reader:
            server = (row.get('server') or '').strip()
            pid = (row.get('player_id') or '').strip()
            name = (row.get('username') or '').strip()
            if not server or not pid or not name:
                continue
            capture = Path(row.get('capture') or '').name
            when = time_map.get(capture, saved_at)
            basis = 'checkpoint completion (approximate)' if capture in time_map else 'CSV saved time (approximate)'
            rows[(server, pid)] = (server, pid, name,
                row.get('alliance_tag') or '', row.get('alliance_name') or '',
                row.get('base_level') or '', row.get('x') or '',
                row.get('y') or '', capture, when, basis)
    now = datetime.now(timezone.utc).isoformat()
    with db:
        cursor = db.execute("""
          INSERT INTO snapshots
          (source,content_sha,saved_at,timestamp_basis,imported_at,row_count)
          VALUES (?,?,?,?,?,?)""",
          (source, digest, saved_at, 'CSV saved time (approximate)', now, len(rows)))
        snapshot_id = cursor.lastrowid
        db.executemany("""
          INSERT INTO observations(snapshot_id,server,player_id,username,
          alliance_tag,alliance_name,base_level,x,y,capture,observed_at,timestamp_basis)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
          [(snapshot_id, *values) for values in rows.values()])
    return 1, len(rows)


def sync(db, root=DEFAULT_ROOT, extra_files=()):
    files = discovery(Path(root))
    files.extend(Path(path) for path in extra_files)
    seen = set()
    imported = observations = 0
    for p in files:
        key = str(p.resolve())
        if key in seen:
            continue
        seen.add(key)
        count, records = import_csv(db, p, root=root)
        imported += count
        observations += records
        if count:
            print(f'Imported {records:,} records from {p}')
    print(f'History sync: {imported} new snapshots, {observations:,} observations. '
          f'{db.execute("SELECT count(*) FROM observations").fetchone()[0]:,} stored total.')
    return imported, observations



def ingest_records(db, records, source, observed_at=None):
    """Append a real capture's currently observed players.

    Unlike importing players.csv, these rows come from individual decoded map
    responses, allowing us to retain renames seen between roster exports.
    Safe to repeat for the same capture; never overwrites previous aliases.
    """
    rows = {}
    for row in records:
        server = str(row.get('server') or '').strip()
        pid = str(row.get('player_id') or '').strip()
        name = str(row.get('username') or '').strip()
        if not server or not pid or not name:
            continue
        rows[(server,pid)] = (server,pid,name,
            str(row.get('alliance_tag') or ''),
            str(row.get('alliance_name') or ''),
            str(row.get('base_level') or ''),
            str(row.get('x') or ''),str(row.get('y') or ''),
            Path(str(row.get('capture') or '')).name)
    if not rows:
        return 0
    if observed_at is None:
        observed_at = datetime.now(timezone.utc).isoformat()
    source = str(source).replace('\\','/')
    # Stable fingerprint for a processed capture; repeated decoding doesn't
    # create duplicate snapshots for unchanged content.
    digest = hashlib.sha256(json.dumps(
        sorted(rows.values()),ensure_ascii=False,separators=(',',':')
    ).encode('utf-8')).hexdigest()
    if db.execute('SELECT 1 FROM snapshots WHERE source=? AND content_sha=?',
                  (source,digest)).fetchone():
        return 0
    basis='decoded map response recorded (approximate)'
    with db:
        cursor=db.execute("""
          INSERT INTO snapshots
          (source,content_sha,saved_at,timestamp_basis,imported_at,row_count)
          VALUES(?,?,?,?,?,?)""",
          (source,digest,observed_at,basis,
           datetime.now(timezone.utc).isoformat(),len(rows)))
        sid=cursor.lastrowid
        db.executemany("""
          INSERT INTO observations
          (snapshot_id,server,player_id,username,alliance_tag,alliance_name,
           base_level,x,y,capture,observed_at,timestamp_basis)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
          [(sid,*row,observed_at,basis) for row in rows.values()])
    return len(rows)


def directory(db, server=None):
    params = [] if server is None else [str(server)]
    sql = """SELECT o.*, s.source, s.id AS source_version
             FROM observations o JOIN snapshots s ON s.id=o.snapshot_id"""
    if server is not None:
        sql += " WHERE o.server=?"
    sql += " ORDER BY o.server, o.player_id, o.observed_at, o.snapshot_id"
    grouped = defaultdict(list)
    for row in db.execute(sql, params):
        grouped[(row['server'], row['player_id'])].append(dict(row))
    result = []
    for (server_code, pid), observations in grouped.items():
        current = observations[-1]
        names = []
        events = []
        for item in observations:
            name = item['username']
            if not names or names[-1]['name'] != name:
                names.append(dict(name=name, first_seen=item['observed_at'],
                                  last_seen=item['observed_at'],
                                  timestamp_basis=item['timestamp_basis'],
                                  source=item['source'], observations=1))
                events.append(dict(name=name, observed_at=item['observed_at'],
                                   timestamp_basis=item['timestamp_basis'],
                                   source=item['source']))
            else:
                names[-1]['last_seen'] = item['observed_at']
                names[-1]['observations'] += 1
        aliases = list(dict.fromkeys(o['username'] for o in observations))
        sources = sorted(set(o['source'] for o in observations))
        result.append(dict(server=server_code, player_id=pid,
                           username=current['username'], x=current['x'],
                           y=current['y'], alliance_tag=current['alliance_tag'],
                           alliance_name=current['alliance_name'],
                           base_level=current['base_level'],
                           snapshot_count=len(observations),
                           source_count=len(sources),
                           first_seen=observations[0]['observed_at'],
                           last_seen=current['observed_at'],
                           time_basis=current['timestamp_basis'],
                           aliases=aliases, name_events=events,
                           observed_name_changes=max(0, len(events)-1)))
    return result


def export(db, out, server=None):
    records = directory(db, server)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Exported {len(records):,} player histories to {out}')


def main():
    parser = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--db', type=Path, default=DEFAULT_DB)
    parser.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('sync', help='Ingest saved CSV snapshots without losing old names')
    p.add_argument('--file', type=Path, action='append', default=[],
                   help='Additional historical player CSV snapshot (repeatable)')
    p = commands.add_parser('show', help='Print observed names for one stable player ID')
    p.add_argument('--id', required=True, help='server:player_id e.g. 125:12345')
    p = commands.add_parser('export', help='Export private player directory with name events')
    p.add_argument('--out', type=Path, default=Path('network_scans/player_directory.json'))
    p.add_argument('--server', type=str, default='125')
    args = parser.parse_args()
    with connection(args.db) as db:
        if args.command == 'sync':
            sync(db, args.root, args.file)
        elif args.command == 'show':
            if ':' not in args.id:
                parser.error('--id must be in the form server:player_id')
            server, pid = args.id.split(':', 1)
            matches = [p for p in directory(db, server) if p['player_id'] == pid]
            if not matches:
                print('Player not found. Run sync or verify the ID.')
                return
            p = matches[0]
            print(f'S{p["server"]} player {p["player_id"]} — latest recorded name: {p["username"]}')
            print(f'{p["snapshot_count"]} snapshots; {len(p["aliases"])} distinct observed names')
            for event in p['name_events']:
                print(f'  {event["observed_at"]}: {event["name"]} '
                      f'({event["timestamp_basis"]}; {event["source"]})')
            print('These are observation timestamps, not exact rename times.')
        else:
            export(db, args.out, args.server)


if __name__ == '__main__':
    main()
