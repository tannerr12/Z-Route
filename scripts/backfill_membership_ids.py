#!/usr/bin/env python3
"""Backfill public Join/Leave player IDs from Server 125's world roster.

This only links exact, globally unambiguous player names / known aliases to
the stable world player_id. No guesses based on partial names, guild,
coordinates, chronology or similar spelling. Original log names remain intact.
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


def enrich_file(world=WORLD,changes=CHANGES,apply=False):
    unique,ambiguous=names_from_roster(world)
    with Path(changes).open(newline="",encoding="utf-8-sig") as stream:
        reader=csv.DictReader(stream)
        header=list(reader.fieldnames or [])
        if not {"player","event"}.issubset(header):
            raise ValueError("Join/Leave CSV missing player or event columns")
        rows=list(reader)
    fields=header+[x for x in ID_FIELDS if x not in header]
    resolved=0;unresolved=0;ambiguous_count=0;conflicts=0
    for row in rows:
        name=normalize(row.get("player"))
        candidate=unique.get(name)
        prior=str(row.get("player_id") or "").strip()
        if candidate and not prior:
            row["player_id"]=candidate
            row["player_id_source"]=SOURCE
            resolved+=1
        elif prior and candidate and candidate!=prior:
            # Do not overwrite evidence from earlier private map history.
            row["player_id_source"]="conflicting_identity"
            conflicts+=1
        elif not prior:
            if name in ambiguous:
                ambiguous_count+=1
            else:
                unresolved+=1
    changed=fields!=header or any(
        any(str(raw.get(k) or "")!=str(row.get(k) or "")
            for k in ID_FIELDS)
        for raw,row in []
    ) or resolved>0 or conflicts>0
    counts=dict(events=len(rows),newly_resolved=resolved,unresolved=unresolved,
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
