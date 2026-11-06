"""Offline tests for recurring passive map-snapshot comparison.

python -m unittest discover -s network_scan -p test_scan_changes.py
"""
import csv
import tempfile
import unittest
from pathlib import Path

from scan_changes import compare,read_snapshot,run
from types import SimpleNamespace
import json


class RefreshComparisonTests(unittest.TestCase):
    def test_move_tracked_by_stable_player_id_not_username(self):
        old={('125','100'):dict(username='Player',x=500,y=421,alliance_tag='D3AD',
                                base_level='27')}
        new={('125','100'):dict(username='RenamedPlayer',x=505,y=423,
                                alliance_tag='D3AD',base_level='27')}
        changes,counts=compare(old,new)
        self.assertEqual(len(changes),1)
        self.assertEqual(counts['coordinates_changed'],1)
        self.assertEqual(counts['observed_in_both'],1)
        self.assertEqual(changes[0]['classification'],'moved+renamed')
        self.assertEqual(changes[0]['manhattan_move'],7)
        self.assertEqual(changes[0]['x_after'],505)

    def test_missing_player_is_not_claimed_removed(self):
        before={('125','1'):dict(username='A',x=1,y=1),
                ('125','2'):dict(username='B',x=2,y=2)}
        after={('125','2'):dict(username='B',x=2,y=2),
               ('125','3'):dict(username='C',x=3,y=3)}
        changes,counts=compare(before,after)
        labels={c['player_id']:c['classification'] for c in changes}
        self.assertEqual(labels['1'],'not_seen_in_after')
        self.assertEqual(labels['3'],'newly_seen')
        self.assertEqual(counts['observed_in_both'],1)
        self.assertEqual(counts['coordinates_changed'],0)

    def test_same_name_different_player_id_not_merged(self):
        before={('125','1'):dict(username='Same',x=10,y=20)}
        after={('125','2'):dict(username='Same',x=10,y=20)}
        changes,counts=compare(before,after)
        self.assertEqual(len(changes),2)
        self.assertEqual(counts['observed_in_both'],0)

    def test_comparing_refreshes_generates_primary_rename_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'network_scans'
            before=root/'map_refresh'/'scan_01'/'players.csv'
            after=root/'map_refresh'/'scan_02'/'players.csv'
            for file,name in ((before,'OldNick'),(after,'NewNick')):
                file.parent.mkdir(parents=True,exist_ok=True)
                with file.open('w',newline='',encoding='utf-8-sig') as out:
                    writer=csv.DictWriter(out,fieldnames=[
                        'server','player_id','username','x','y','alliance_tag'])
                    writer.writeheader()
                    writer.writerow(dict(server=125,player_id=9001,username=name,
                                         x=502,y=420,alliance_tag='D3AD'))
            # Force distinct observed times so the change is chronological.
            import os
            os.utime(before,(1700000000,1700000000))
            os.utime(after,(1700003600,1700003600))
            out=root/'results'
            run(SimpleNamespace(before=before,after=after,out=out,server=125,
                                network_root=root,history_db=root/'player_history.sqlite3'))
            with (out/'renames.csv').open(encoding='utf-8-sig') as stream:
                entries=list(csv.DictReader(stream))
            self.assertEqual(len(entries),1)
            self.assertEqual(entries[0]['username_before'],'OldNick')
            self.assertEqual(entries[0]['username_after'],'NewNick')
            with (out/'all_name_changes.csv').open(encoding='utf-8-sig') as stream:
                lifetime=list(csv.DictReader(stream))
            self.assertEqual(len(lifetime),1)
            self.assertEqual(lifetime[0]['old_name'],'OldNick')
            self.assertEqual(lifetime[0]['new_name'],'NewNick')
            summary=json.loads((out/'summary.json').read_text(encoding='utf-8'))
            self.assertEqual(summary['names_changed'],1)
            self.assertEqual(summary['lifetime_observed_name_changes'],1)
            self.assertEqual(summary['coordinates_changed'],0)

    def test_schema_rejects_swipe_grid(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'old.csv'
            path.write_text('username,row,col\\nA,1,2\\n',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'world-coordinate'):
                read_snapshot(path,125)

    def test_csv_reads_exact_positions_and_server(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'bases.csv'
            with path.open('w',newline='',encoding='utf-8-sig') as out:
                writer=csv.DictWriter(out,fieldnames=(
                    'server','player_id','username','x','y','base_level'))
                writer.writeheader()
                writer.writerow(dict(server=125,player_id=1,username='A',
                                     x=500,y=400,base_level=26))
                writer.writerow(dict(server=126,player_id=2,username='Other',
                                     x=600,y=400,base_level=25))
            result=read_snapshot(path,125)
            self.assertEqual(set(result),{('125','1')})
            self.assertEqual(result[('125','1')]['x'],500)


if __name__=='__main__':
    unittest.main()
