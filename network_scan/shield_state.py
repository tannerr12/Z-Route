#!/usr/bin/env python3
"""Z-Route player-base shield interpretation (operationally confirmed S125 rule).

For complete decoded player-base records:
  protobuf player detail field 9 == 1  -> shielded
  field 9 absent                       -> unshielded
  any other field 9 value              -> unknown

Validated against 3 visually shielded player bases (Appsie213,
BigDaddyKane, Crazy72) and 1 visually unshielded base (DrDs). The
raw field and observation timestamp are retained. This mapping is
the project's accepted rule, not a claim of an official game API.

A missing *player record* never implies unshielded.
Snapshots older than max_age_minutes become "unknown" for current
display even though their historic observed status is preserved.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone, timedelta
from pathlib import Path


def decode_shield_status(raw):
    """Decode a field-9 value from one existing, decoded player-base record."""
    if raw is None or (isinstance(raw,str) and not raw.strip()):
        return 'unshielded'
    try:
        if isinstance(raw,bool):
            return 'unknown'
        return 'shielded' if str(raw).strip()=='1' else 'unknown'
    except (TypeError,ValueError):
        return 'unknown'


def parse_observed_at(raw):
    if not raw:
        return None
    try:
        timestamp=datetime.fromisoformat(str(raw).strip().replace('Z','+00:00'))
        if timestamp.tzinfo is None:
            return None
        return timestamp.astimezone(timezone.utc)
    except (ValueError,TypeError,OverflowError):
        return None


def latest_shield_observations(network_root, server=125, max_age_minutes=60, now=None):
    """Aggregate latest passive player records by *stable* (server, player ID).

    Includes all entity_live session CSVs; never infers status of a player
    omitted from the latest viewport. Status is unknown when the latest
    observation is stale relative to now.
    """
    network_root=Path(network_root)
    now=(now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if max_age_minutes is not None and max_age_minutes<0:
        raise ValueError('max_age_minutes must be >= 0 or None')
    latest={}
    files=sorted((network_root/'entity_live').glob('*/player_status_sightings.csv'))
    for file in files:
        try:
            stream=file.open('r',newline='',encoding='utf-8-sig')
        except OSError:
            continue
        with stream:
            reader=csv.DictReader(stream)
            if not {'server','player_id','seen_at_utc'}.issubset(set(reader.fieldnames or ())):
                continue
            for row in reader:
                if str(row.get('server') or '').strip()!=str(server):
                    continue
                pid=str(row.get('player_id') or '').strip()
                observed=parse_observed_at(row.get('seen_at_utc'))
                if not pid or observed is None:
                    continue
                key=(str(server),pid)
                current=latest.get(key)
                if current is not None and observed<=current['_time']:
                    continue
                raw=row.get('status_9')
                observed_status=decode_shield_status(raw)
                latest[key]=dict(
                    shield_status=observed_status,
                    recorded_shield_status=observed_status,
                    shield_field_9='' if raw is None else str(raw).strip(),
                    shield_observed_at_utc=observed.isoformat(),
                    shield_capture=row.get('capture') or '',
                    shield_source_session=file.parent.name,
                    _time=observed)
    for result in latest.values():
        observed=result.pop('_time')
        age=now-observed
        if age.total_seconds()<0 or (
            max_age_minutes is not None and age>timedelta(minutes=max_age_minutes)):
            result['shield_status']='unknown'
        result['shield_age_minutes']=round(age.total_seconds()/60,1)
    return latest
