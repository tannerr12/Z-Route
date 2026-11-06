"""Offline tests for private shield-status calibration.

Run: python -m unittest discover -s network_scan -p test_shield_probe.py
No Wireshark, BlueStacks or server traffic needed.
"""
import csv
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from datetime import datetime,timezone

from live_entity_watch import append_csv,STATUS_FIELDS
from shield_probe import (MARK_FIELDS, assign_marks, cohort_samples,
                          compare_fields, detail_map, mark, read_csv,
                          require_session, resolve_player, session_diagnostics)


class ShieldCalibrationTests(unittest.TestCase):
    def test_diagnostics_flags_markers_newer_than_all_capture_files(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from live_entity_watch import SEG_FIELDS
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)
            append_csv(path/'segments.csv',SEG_FIELDS,[dict(
                file='old.pcapng',observed_at_utc='2026-11-06T18:28:40+00:00',
                decoded_views=3,decoded_updates=0)])
            append_csv(path/'player_status_sightings.csv',STATUS_FIELDS,[
                dict(server=125,player_id='1234',username='BlueBase',
                     x=502,y=423,seen_at_utc='2026-11-06T18:28:40+00:00')])
            markers=[dict(server=125,player_id='1234',username='BlueBase',
                         state='shielded',
                         marked_at_utc='2026-11-06T18:36:22+00:00')]
            output=StringIO()
            with redirect_stdout(output):
                state=session_diagnostics(path,125,markers,90)
            self.assertIn('no processed capture window after this marker',
                          output.getvalue())
            self.assertIn('18:28:40',state['last_player'].isoformat())

    def test_diagnostics_separates_other_base_updates_from_target_updates(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from live_entity_watch import SEG_FIELDS
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)
            append_csv(path/'segments.csv',SEG_FIELDS,[dict(
                file='new.pcapng',observed_at_utc='2026-11-06T18:37:10+00:00',
                decoded_views=3,decoded_updates=1)])
            append_csv(path/'player_status_sightings.csv',STATUS_FIELDS,[
                dict(server=125,player_id='2222',username='Other',
                     seen_at_utc='2026-11-06T18:37:10+00:00')])
            markers=[dict(server=125,player_id='1234',username='BlueBase',
                         state='shielded',
                         marked_at_utc='2026-11-06T18:36:22+00:00')]
            output=StringIO()
            with redirect_stdout(output):
                session_diagnostics(path,125,markers,90)
            self.assertIn('no NEW decoded base sighting for this player',
                          output.getvalue())

    def test_placeholder_session_is_rejected_with_actionable_error(self):
        with tempfile.TemporaryDirectory() as td:
            fake=Path(td)/'SESSION'
            with self.assertRaisesRegex(ValueError,'SESSION is a placeholder'):
                require_session(fake)

    def test_real_existing_session_is_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(require_session(Path(td)),Path(td))

    def test_cohort_fields_are_after_visual_marker_and_per_player(self):
        marks=[
            dict(server=125,player_id='100',state='shielded',
                 marked_at_utc='2026-11-06T18:28:30+00:00',username='BlueBase'),
            dict(server=125,player_id='101',state='unshielded',
                 marked_at_utc='2026-11-06T18:28:30+00:00',username='NoDome')]
        rows=[
            dict(server=125,player_id='100',username='BlueBase',
                 seen_at_utc='2026-11-06T18:28:29+00:00',status_9=''),
            dict(server=125,player_id='100',username='BlueBase',
                 seen_at_utc='2026-11-06T18:28:40+00:00',status_9='1'),
            dict(server=125,player_id='101',username='NoDome',
                 seen_at_utc='2026-11-06T18:28:40+00:00',status_9=''),
            dict(server=125,player_id='102',username='Unmarked',
                 seen_at_utc='2026-11-06T18:28:40+00:00',status_9='1')]
        evidence=cohort_samples(marks,rows,125,60)
        self.assertEqual(len(evidence),2)
        self.assertEqual({e['state']:e['status_9'] for e in evidence},
                         {'shielded':'1','unshielded':''})
        self.assertTrue(all(e['observed_at_utc']>e['marked_at_utc'] for e in evidence))

    def test_cohort_marks_without_post_marker_sighting_not_used(self):
        marks=[dict(server=125,player_id='100',state='shielded',
                    marked_at_utc='2026-11-06T18:28:30+00:00')]
        rows=[dict(server=125,player_id='100',seen_at_utc='2026-11-06T18:28:20+00:00',
                   status_9='1')]
        self.assertEqual(cohort_samples(marks,rows,125,60),[])

    def test_all_detail_fields_preserved_without_guessing_flag_names(self):
        detail=[(1,0,1234),(2,0,27),(4,2,b'TestPlayer'),
                (9,0,1),(18,0,1793932531824),(30,2,b'\xff\xfe')]
        fields=detail_map(detail)
        self.assertEqual(fields['9:0'],('1',))
        self.assertEqual(fields['4:2'],('TestPlayer',))
        self.assertEqual(fields['30:2'],('0xfffe',))
        self.assertNotIn('shield_status',fields)

    def test_comparison_flags_correlations_not_confirms(self):
        base={'1:0':('1234',),'4:2':('User',),'9:0':('1',)}
        samples=[
            {'state_marker':'shielded','details':dict(base,**{'15:0':('1',),'18:0':('100',)})},
            {'state_marker':'shielded','details':dict(base,**{'15:0':('1',),'18:0':('102',)})},
            {'state_marker':'unshielded','details':dict(base,**{'15:0':('2',),'18:0':('200',)})},
            {'state_marker':'unshielded','details':dict(base,**{'15:0':('2',),'18:0':('205',)})},
        ]
        diffs,on,off=compare_fields(samples)
        self.assertEqual((on,off),(2,2))
        self.assertEqual([r['field_path'] for r in diffs],['15:0','18:0'])
        self.assertEqual(diffs[0]['interpretation'],'consistent_difference_UNVERIFIED')
        self.assertEqual(diffs[1]['interpretation'],'variable_difference_UNVERIFIED')

    def test_repeated_view_counts_are_not_field_differences(self):
        samples=([{'state_marker':'shielded','details':{'9:0':('1',)}}]*3
                 +[{'state_marker':'unshielded','details':{'9:0':('1',)}}])
        diffs,_,_=compare_fields(samples)
        self.assertEqual(diffs,[])

    def test_mark_uses_stable_player_identity_not_name(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)
            append_csv(path/'player_status_sightings.csv',STATUS_FIELDS,[
                dict(seen_at_utc='2026-11-06T12:00:00+00:00',
                     server=125,player_id=1234,username='OldName',x=500,y=400),
                dict(seen_at_utc='2026-11-06T12:01:00+00:00',
                     server=125,player_id=1234,username='NewName',x=500,y=400)])
            who=resolve_player(path,125,None,500,400)
            self.assertEqual(who['player_id'],'1234')
            self.assertEqual(who['username'],'NewName')
            args=SimpleNamespace(session=path,state='shielded',
                server=125,player_id=None,username=None,x=500,y=400,evidence=None,note='')
            with patch('shield_probe.utc_now',return_value='2026-11-06T12:02:00+00:00'):
                mark(args)
            result=read_csv(path/'shield_marks.csv')
            self.assertEqual(len(result),1)
            self.assertEqual(result[0]['state'],'shielded')
            self.assertEqual(result[0]['player_id'],'1234')
            self.assertEqual(result[0]['x'],'500')

    def test_find_shield_candidate_by_exact_username_without_coordinates(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)
            append_csv(path/'player_status_sightings.csv',STATUS_FIELDS,[
                dict(seen_at_utc='2026-11-06T18:30:00+00:00',
                     server=125,player_id=111,username='BigDaddyKane',
                     x=300,y=420,status_9=1),
                dict(seen_at_utc='2026-11-06T18:30:05+00:00',
                     server=125,player_id=222,username='Unrelated',
                     x=301,y=420,status_9='')])
            matched=resolve_player(path,125,username='bigdaddykane')
            self.assertEqual(str(matched['player_id']),'111')
            self.assertEqual((str(matched['x']),str(matched['y'])),('300','420'))
            args=SimpleNamespace(session=path,server=125,player_id=None,
                                 username='BigDaddyKane',x=None,y=None,
                                 evidence=None,note='',state='shielded')
            with patch('shield_probe.utc_now',return_value='2026-11-06T18:31:00+00:00'):
                mark(args)
            saved=read_csv(path/'shield_marks.csv')
            self.assertEqual(saved[0]['player_id'],'111')
            self.assertEqual(saved[0]['state'],'shielded')

    def test_same_username_for_multiple_player_ids_refused(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)
            append_csv(path/'player_status_sightings.csv',STATUS_FIELDS,[
                dict(server=125,player_id=111,username='BigDaddyKane',x=300,y=420),
                dict(server=125,player_id=222,username='BigDaddyKane',x=301,y=420)])
            with self.assertRaisesRegex(ValueError,'Multiple player IDs'):
                resolve_player(path,125,username='BigDaddyKane')

    def test_unknown_username_requires_fresh_capture(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)
            append_csv(path/'player_status_sightings.csv',STATUS_FIELDS,[
                dict(server=125,player_id=111,username='Other',x=300,y=420)])
            with self.assertRaisesRegex(ValueError,'No saved player-base observation matching username'):
                resolve_player(path,125,username='BigDaddyKane')

    def test_multiple_player_ids_at_same_coordinate_refused(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)
            append_csv(path/'player_status_sightings.csv',STATUS_FIELDS,[
                dict(server=125,player_id=1,username='A',x=500,y=400),
                dict(server=125,player_id=2,username='B',x=500,y=400)])
            with self.assertRaisesRegex(ValueError,'Multiple player IDs'):
                resolve_player(path,125,None,500,400)

    def test_association_respects_marker_order_and_window(self):
        marks=[
            dict(marked_at_utc='2026-11-06T12:00:00+00:00',
                 state='shielded'),
            dict(marked_at_utc='2026-11-06T12:01:00+00:00',
                 state='unshielded')]
        observations=[
            dict(observed_at_utc='2026-11-06T11:59:55+00:00',details={}),
            dict(observed_at_utc='2026-11-06T12:00:10+00:00',details={}),
            dict(observed_at_utc='2026-11-06T12:00:59+00:00',details={}),
            dict(observed_at_utc='2026-11-06T12:01:15+00:00',details={})]
        labeled=assign_marks(observations,marks,30)
        self.assertEqual([r['state_marker'] for r in labeled],
                         ['shielded','unshielded'])
        self.assertEqual(labeled[0]['observed_at_utc'],
                         '2026-11-06T12:00:10+00:00')


if __name__=='__main__':
    unittest.main()
