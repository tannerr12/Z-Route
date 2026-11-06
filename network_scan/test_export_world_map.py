"""Offline tests for export_world_map.py.

python -m unittest discover -s network_scan -p test_export_world_map.py
"""
from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from export_world_map import build_world_roster, export, safe_integer


class ExactWorldMapExportTests(unittest.TestCase):
    def test_coordinates_not_swipe_grid(self):
        raw=[
            dict(server='125',player_id='11',username='A',x='502',y='423',
                 row='1',col='70',base_level='27',alliance_tag='D3AD'),
            dict(server='125',player_id='12',username='B',x='514',y='411',
                 row='40',col='4',base_level='25'),
        ]
        people,skipped=build_world_roster(
            raw,125,'2026-11-06T20:00:00+00:00',{})
        self.assertEqual(skipped,0)
        self.assertEqual(len(people),2)
        self.assertEqual((people[0]['x'],people[0]['y']),(502,423))
        self.assertEqual((people[1]['x'],people[1]['y']),(514,411))
        self.assertEqual(people[0]['base_level'],27)
        self.assertEqual(people[0]['coordinate_source'],'passive_network_world_xy')
        self.assertEqual(people[0]['shield_status'],'unknown')

    def test_identity_is_server_and_player_id_not_name(self):
        raw=[
            dict(server='125',player_id='11',username='SameName',x='502',y='423'),
            dict(server='125',player_id='12',username='SameName',x='514',y='411'),
            dict(server='125',player_id='11',username='Renamed',x='517',y='422'),
            dict(server='126',player_id='11',username='WrongServer',x='1',y='1'),
            dict(server='125',player_id='bad',username='BadCoordinate',x='',y='10'),
        ]
        people,skipped=build_world_roster(raw,125,'',{})
        self.assertEqual(len(people),2)
        self.assertEqual(skipped,1)
        self.assertEqual({p['player_id']:p['x'] for p in people},
                         {'11':517,'12':514})

    def test_world_export_retains_current_name_and_every_previous_alias(self):
        raw=[dict(server=125,player_id=111,username='OldNick',
                  x=502,y=423,base_level=25)]
        events=[
            dict(old_name='OldNick',new_name='NewNick',
                 last_old_observed_at_utc='2026-11-06T18:00:00+00:00',
                 first_new_observed_at_utc='2026-11-06T19:00:00+00:00')]
        history={'111':dict(username='NewNick',aliases=['OldNick','NewNick'],
                           rename_history=events,last_seen='2026-11-06T19:00:00+00:00')}
        people,_=build_world_roster(raw,125,'2026-11-06T19:10:00+00:00',
                                    {},history)
        result=people[0]
        self.assertEqual(result['username'],'NewNick')
        self.assertEqual(result['observed_name_changes'],1)
        self.assertEqual(json.loads(result['known_aliases_json']),['OldNick','NewNick'])
        self.assertEqual(json.loads(result['name_history_json']),events)
        self.assertEqual((result['x'],result['y']),(502,423))

    def test_shield_metadata_joined_only_from_matching_player_id(self):
        raw=[dict(server=125,player_id='111',username='Blue',
                  x=10,y=20,base_level=25)]
        shield={('125','111'):dict(shield_status='shielded',
                recorded_shield_status='shielded',shield_field_9='1',
                shield_observed_at_utc='2026-11-06T20:00:00+00:00')}
        people,_=build_world_roster(raw,125,'',shield)
        self.assertEqual(people[0]['shield_status'],'shielded')
        self.assertEqual(people[0]['shield_field_9'],'1')

    def test_export_writes_local_exact_world_csv(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            roster=root/'combined_players.csv'
            with roster.open('w',encoding='utf-8-sig',newline='') as f:
                writer=csv.DictWriter(f,fieldnames=[
                    'server','player_id','username','x','y',
                    'base_level','alliance_tag','capture'])
                writer.writeheader()
                writer.writerow(dict(server=125,player_id=77,
                    username='TestBase',x=500,y=400,
                    base_level=28,alliance_tag='D3AD',capture='scan.pcapng'))
            out=root/'data'/'world-players.csv'
            args=SimpleNamespace(roster=roster,out=out,network_root=root,
                    server=125,max_shield_age_minutes=60,no_shields=True)
            export(args)
            with out.open(encoding='utf-8-sig',newline='') as f:
                people=list(csv.DictReader(f))
            self.assertEqual(len(people),1)
            self.assertEqual(people[0]['player_id'],'77')
            self.assertEqual(people[0]['x'],'500')
            self.assertEqual(people[0]['y'],'400')
            self.assertEqual(people[0]['base_level'],'28')
            self.assertEqual(people[0]['shield_status'],'unknown')
            self.assertTrue(people[0]['roster_snapshot_at_utc'])

    def test_rejects_invalid_source_schema_without_clobbering_output(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            roster=root/'legacy.csv'
            roster.write_text('username,guild,level,row,col\nA,D3AD,27,1,2\n',
                              encoding='utf-8')
            out=root/'map.csv'
            out.write_text('do not overwrite',encoding='utf-8')
            args=SimpleNamespace(roster=roster,out=out,network_root=root,
                    server=125,max_shield_age_minutes=60,no_shields=True)
            with self.assertRaisesRegex(ValueError,'not a network world-coordinate roster'):
                export(args)
            self.assertEqual(out.read_text(encoding='utf-8'),'do not overwrite')

    def test_noninteger_and_out_of_bounds_positions_rejected(self):
        self.assertIsNone(safe_integer('1.25'))
        self.assertIsNone(safe_integer(''))
        self.assertIsNone(safe_integer('-1'))
        self.assertIsNone(safe_integer('5001'))
        self.assertEqual(safe_integer('1000'),1000)


if __name__=='__main__':
    unittest.main()
