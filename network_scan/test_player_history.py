"""Offline regression tests for persistent player ID / name history.

Run: python -m unittest discover -s network_scan -p test_player_history.py
"""
import csv
import json
import os
import tempfile
import unittest
from pathlib import Path

from player_history import connection, directory, import_csv, ingest_records, sync
from coverage_report import bin_data, build, read_roster
from types import SimpleNamespace


def write_roster(path, records, seconds):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8-sig') as stream:
        cols = ['server','player_id','username','x','y',
                'alliance_tag','alliance_name','base_level','capture','time_s']
        writer = csv.DictWriter(stream, fieldnames=cols)
        writer.writeheader()
        writer.writerows(records)
    os.utime(path,(seconds,seconds))


class IdentityHistoryTests(unittest.TestCase):
    def test_name_changes_preserve_stable_player_key(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / 'network_scans'
            first = root / 'live' / 'sessionA' / 'players.csv'
            second = root / 'live' / 'sessionB' / 'players.csv'
            a = dict(server='125',player_id='abc123',username='OldNick',
                     x='400',y='500',alliance_tag='D3AD',alliance_name='',
                     base_level='25',capture='a.pcapng',time_s='10')
            write_roster(first,[a],1700000000)
            renamed = dict(a,username='NewNick',x='401',y='501')
            write_roster(second,[renamed],1700003600)
            with connection(root / 'history.sqlite3') as db:
                self.assertEqual(sync(db,root),(2,2))
                self.assertEqual(sync(db,root),(0,0))
                result=directory(db,'125')
                self.assertEqual(len(result),1)
                p=result[0]
                self.assertEqual(p['username'],'NewNick')
                self.assertEqual(p['aliases'],['OldNick','NewNick'])
                self.assertEqual(p['observed_name_changes'],1)
                self.assertEqual(p['snapshot_count'],2)

    def test_new_capture_preserves_alias_between_csv_exports(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            with connection(root/'history.sqlite3') as db:
                original=dict(server=125,player_id='42',username='First',
                              x=1,y=2,capture='one.pcapng')
                second=dict(original,username='Second')
                self.assertEqual(ingest_records(db,[original],
                    'live/test/captures/one.pcapng','2026-11-06T08:00:00+00:00'),1)
                self.assertEqual(ingest_records(db,[original],
                    'live/test/captures/one.pcapng','2026-11-06T08:00:00+00:00'),0)
                self.assertEqual(ingest_records(db,[second],
                    'live/test/captures/two.pcapng','2026-11-06T08:05:00+00:00'),1)
                result=directory(db,'125')
                self.assertEqual(result[0]['aliases'],['First','Second'])
                self.assertEqual(result[0]['observed_name_changes'],1)

    def test_same_player_id_different_server_is_distinct(self):
        with tempfile.TemporaryDirectory() as td:
            with connection(Path(td)/'history.sqlite3') as db:
                ingest_records(db,[dict(server=125,player_id=5,username='A'),
                                  dict(server=126,player_id=5,username='B')],
                    'capture1','2026-11-06T08:00:00+00:00')
                self.assertEqual(len(directory(db)),2)

    def test_coverage_with_aliases_generates_private_html(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'network_scans'
            old=root/'live'/'session1'/'players.csv'
            new=root/'full_map'/'players.csv'
            row=dict(server='125',player_id='123',username='Old',x='400',y='510',
                     alliance_tag='D3AD',alliance_name='',base_level='27',
                     capture='first.pcapng',time_s='5')
            write_roster(old,[row],1700000000)
            write_roster(new,[dict(row,username='New')],1700003600)
            combined=root/'combined_players.csv'
            write_roster(combined,[dict(row,username='New')],1700004000)
            args=SimpleNamespace(players=combined,server=125,old=old,new=new,
                network_root=root,views=None,checkpoint=None,bounds=None,
                grid=6,top=3,out=root/'coverage',history_db=root/'history.sqlite3',
                history_file=[],no_sync=False)
            result=build(args)
            self.assertEqual(result['unique_ids'],1)
            self.assertEqual(result['players_with_observed_renames'],1)
            html=(args.out/'coverage.html').read_text(encoding='utf-8')
            self.assertIn('Old',html)
            self.assertIn('New',html)
            self.assertIn('Player directory & name history',html)
            self.assertIn('\"observed_name_changes\":1',html)

    def test_player_density_and_review_gap_are_distinct(self):
        players={'125:1':dict(x=500,y=600),
                 '125:2':dict(x=505,y=600)}
        old={'125:1'}; new={'125:1','125:2'}
        centers=[dict(x=500,y=600,source='grid')]
        cells,review,outside=bin_data(players,old,new,centers,[0,0,1000,1000],10,5)
        self.assertEqual(sum(c['player_count'] for c in cells),2)
        self.assertEqual(sum(c['view_centers_in_cell'] for c in cells),1)
        self.assertEqual(sum(c['shared'] for c in cells),1)
        self.assertEqual(sum(c['new_only'] for c in cells),1)
        self.assertTrue(all(r['reason'].startswith('Far from recorded') for r in review))


if __name__=='__main__':
    unittest.main()
