"""Offline test cases for public player-ID backfill."""
import csv
import json
import tempfile
import unittest
from pathlib import Path

from backfill_membership_ids import enrich_file


class BackfillTests(unittest.TestCase):
    def test_most_recent_timestamped_name_wins_when_exact_alias_shared(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);world=root/"world.csv";changes=root/"changes.csv"
            fields=["server","player_id","username","known_aliases_json",
                    "name_observed_at_utc","name_history_json"]
            with world.open("w",newline="",encoding="utf-8") as stream:
                writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
                writer.writerow(dict(server="125",player_id="101",username="NewA",
                    known_aliases_json='["Shared"]',
                    name_observed_at_utc="2026-11-10T14:00:00+00:00",
                    name_history_json=json.dumps([dict(old_name="Shared",
                    last_old_observed_at_utc="2026-11-08T12:00:00+00:00",
                    new_name="NewA",first_new_observed_at_utc="2026-11-10T14:00:00+00:00")])))
                writer.writerow(dict(server="125",player_id="202",username="Shared",
                    known_aliases_json='["Shared"]',
                    name_observed_at_utc="2026-11-12T15:00:00+00:00",
                    name_history_json="[]"))
            with changes.open("w",newline="",encoding="utf-8") as stream:
                writer=csv.DictWriter(stream,fieldnames=["player","event"])
                writer.writeheader();writer.writerow(dict(player="Shared",event="removed"))
            stats=enrich_file(world,changes,apply=True)
            self.assertEqual(stats["recent_match_resolved"],1)
            with changes.open(newline="",encoding="utf-8") as stream:
                result=list(csv.DictReader(stream))[0]
            self.assertEqual(result["player_id"],"202")
            self.assertEqual(result["player_id_source"],"latest_name_observation_s125")

    def test_equal_or_undated_shared_name_remains_unresolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);world=root/"world.csv";changes=root/"changes.csv"
            fields=["server","player_id","username","known_aliases_json",
                    "name_observed_at_utc","name_history_json"]
            with world.open("w",newline="",encoding="utf-8") as stream:
                writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
                for pid in ("101","202"):
                    writer.writerow(dict(server="125",player_id=pid,
                        username="Same",known_aliases_json='["Same"]',
                        name_observed_at_utc="2026-11-12T12:00:00+00:00",
                        name_history_json="[]"))
            with changes.open("w",newline="",encoding="utf-8") as stream:
                writer=csv.DictWriter(stream,fieldnames=["player","event"])
                writer.writeheader();writer.writerow(dict(player="Same",event="removed"))
            stats=enrich_file(world,changes,apply=True)
            self.assertEqual(stats["recent_match_resolved"],0)
            self.assertEqual(stats["ambiguous"],1)
            with changes.open(newline="",encoding="utf-8") as stream:
                result=list(csv.DictReader(stream))[0]
            self.assertEqual(result["player_id"],"")

    def test_only_unique_aliases_get_ids_and_existing_ids_stay(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);world=root/"world.csv";changes=root/"changes.csv"
            with world.open("w",encoding="utf-8",newline="") as stream:
                writer=csv.DictWriter(stream,fieldnames=[
                    "server","player_id","username","known_aliases_json"])
                writer.writeheader()
                for server,pid,name,aliases in [
                    ("125","101","NewName",["OldName"]),
                    ("125","202","New2",["Shared"]),
                    ("125","303","New3",["Shared"]),
                    ("115","999","Different",["OtherServer"]),
                ]:
                    writer.writerow(dict(server=server,player_id=pid,
                       username=name,known_aliases_json=json.dumps(aliases)))
            with changes.open("w",encoding="utf-8",newline="") as stream:
                writer=csv.DictWriter(stream,fieldnames=["player","event","player_id"])
                writer.writeheader()
                for p,event,pid in [
                    ("OldName","removed",""),("Shared","removed",""),
                    ("OtherServer","removed",""),("NewName","joined",""),
                    ("OldName","removed","404")]:
                    writer.writerow(dict(player=p,event=event,player_id=pid))
            result=enrich_file(world,changes,apply=True)
            self.assertEqual(result["newly_resolved"],2)
            self.assertEqual(result["ambiguous"],1)
            self.assertEqual(result["conflicts"],1)
            with changes.open(newline="",encoding="utf-8") as stream:
                rows=list(csv.DictReader(stream))
            self.assertEqual([r["player_id"] for r in rows],
                             ["101","","","101","404"])
            self.assertEqual(rows[4]["player_id_source"],"conflicting_identity")
            second=enrich_file(world,changes,apply=True)
            self.assertEqual(second["newly_resolved"],0)
            self.assertEqual([r["event"] for r in rows],
                             ["removed","removed","removed","joined","removed"])


if __name__=="__main__":
    unittest.main()
