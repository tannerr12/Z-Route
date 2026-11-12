#!/usr/bin/env python3
"""Backfill public Join/Leave player IDs from Server 125's world roster.

First links unique exact names / aliases. If the same name belongs to
multiple player IDs, chooses the most recently *observed* exact name only
when its timestamp ranks strictly above all competing observations. This
is a heuristic (not proof of identity), tracked by player_id_source.
No fuzzy matching; existing ID assignments remain unchanged.
It is safe to re-run after every world scan or Player Activity publication.
"""
from __future__ import annotations

import argparse
import csv
import json
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
WORLD=ROOT/"data/servers/125/world-players.csv"
CHANGES=ROOT/"data/player_activity/guild_changes.csv"
ID_FIELDS=("player_id","player_id_source")
SOURCE="unique_world_roster_alias_s125"


def normalize(text):
    return " ".join(unicodedata.normalize("NFKC",str(text or "")).split()).casefold()


def names_from_roster(path):
    candidates=defaultdict(set)
    with Path(path).open(newline="",encoding="utf-8-sig") as stream:
        reader=csv.DictReader(stream)
        needed={"server","player_id","username","known_aliases_json"}
        if not needed.issubset(reader.fieldnames or []):
            raise ValueError("World roster missing required identity columns")
        for row in reader:
            if str(row.get("server") or "").strip()!="125":
                continue
            pid=str(row.get("player_id") or "").strip()
            if not pid:
                continue
            names=[row.get("username") or ""]
            try:
                aliases=json.loads(row.get("known_aliases_json") or "[]")
                if isinstance(aliases,list):
                    names.extend(a for a in aliases if isinstance(a,str))
            except (TypeError,ValueError):
                pass
            for name in names:
                nk=normalize(name)
                if nk:
                    candidates[nk].add(pid)
    unique={name:next(iter(ids)) for name,ids in candidates.items()
            if len(ids)==1}
    ambiguous={name for name,ids in candidates.items() if len(ids)>1}
    return unique,ambiguous


def recently_observed_names(path):
    """Ambiguous exact names -> newest observed ID with unique timestamp.

    Name observation history provides stronger evidence than a last-modified
    export timestamp. Never use roster publish time to infer an alias's age.
    Only timestamped evidence about that EXACT name counts.
    """
    seen=defaultdict(dict)
    with Path(path).open(newline="",encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            if str(row.get("server") or "").strip()!="125":
                continue
            pid=str(row.get("player_id") or "").strip()
            if not pid:
                continue
            observations=[]
            current=normalize(row.get("username"))
            current_time=str(row.get("name_observed_at_utc") or "").strip()
            if current and current_time:
                observations.append((current,current_time))
            try:
                history=json.loads(row.get("name_history_json") or "[]")
            except (TypeError,ValueError):
                history=[]
            if isinstance(history,list):
                for change in history:
                    if not isinstance(change,dict):
                        continue
                    for name_field,stamp_field in (
                        ("old_name","last_old_observed_at_utc"),
                        ("new_name","first_new_observed_at_utc")):
                        name=normalize(change.get(name_field))
                        stamp=str(change.get(stamp_field) or "").strip()
                        if name and stamp:
                            observations.append((name,stamp))
            for name,stamp in observations:
                # ISO8601 timestamps sort lexicographically in UTC; parse
                # into comparable epoch values to handle different offsets.
                from datetime import datetime,timezone
                try:
                    moment=datetime.fromisoformat(stamp.replace("Z","+00:00"))
                    if moment.tzinfo is None:
                        continue
                    epoch=moment.astimezone(timezone.utc).timestamp()
                except (ValueError,OverflowError):
                    continue
                old=seen[name].get(pid)
                if old is None or epoch>old:
                    seen[name][pid]=epoch
    recent={}
    for name,entries in seen.items():
        if len(entries)<2:
            continue
        ranking=sorted(entries.items(),key=lambda entry:entry[1],reverse=True)
        # A tie cannot be disambiguated by recency.
        if ranking[0][1]>ranking[1][1]:
            recent[name]=ranking[0][0]
    return recent


def enrich_file(world=WORLD,changes=CHANGES,apply=False):
    unique,ambiguous=names_from_roster(world)
    recent=recently_observed_names(world)
    with Path(changes).open(newline="",encoding="utf-8-sig") as stream:
        reader=csv.DictReader(stream)
        header=list(reader.fieldnames or [])
        if not {"player","event"}.issubset(header):
            raise ValueError("Join/Leave CSV missing player or event columns")
        rows=list(reader)
    fields=header+[x for x in ID_FIELDS if x not in header]
    resolved=0;recent_resolved=0;unresolved=0;ambiguous_count=0;conflicts=0
    for row in rows:
        name=normalize(row.get("player"))
        candidate=unique.get(name) or (recent.get(name) if name in ambiguous else None)
        source=SOURCE if name in unique else "latest_name_observation_s125"
        prior=str(row.get("player_id") or "").strip()
        if candidate and not prior:
            row["player_id"]=candidate
            row["player_id_source"]=source
            resolved+=1
            if source!="unique_world_roster_alias_s125":
                recent_resolved+=1
        elif prior and candidate and candidate!=prior:
            # Do not overwrite evidence from earlier private map history.
            row["player_id_source"]="conflicting_identity"
            conflicts+=1
        elif not prior:
            if name in ambiguous:
                ambiguous_count+=1
            else:
                unresolved+=1
    changed=fields!=header or resolved>0 or conflicts>0
    counts=dict(events=len(rows),newly_resolved=resolved,
                recent_match_resolved=recent_resolved,unresolved=unresolved,
                ambiguous=ambiguous_count,conflicts=conflicts,
                with_id=sum(bool(row.get("player_id")) for row in rows),
                unique_names=len(unique))
    print("[membership/id]",counts,flush=True)
    if apply and changed:
        staged=Path(str(changes)+".tmp")
        try:
            with staged.open("w",newline="",encoding="utf-8") as stream:
                writer=csv.DictWriter(stream,fieldnames=fields,
                                      extrasaction="ignore")
                writer.writeheader();writer.writerows(rows)
            staged.replace(changes)
            print("[membership/id] Published CSV backfilled.",flush=True)
        finally:
            staged.unlink(missing_ok=True)
    return counts


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--apply",action="store_true")
    args=p.parse_args()
    enrich_file(apply=args.apply)


if __name__=="__main__":
    main()
