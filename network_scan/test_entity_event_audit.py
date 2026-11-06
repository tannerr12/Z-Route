"""Offline tests for manual Walker event markers and non-despawn inferences."""
import csv
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from datetime import datetime,timezone

from entity_event_audit import (compare_sightings,cutoff_from_marks,
                                mark,message_stats,parse_time)
from live_entity_watch import append_csv,EVENT_FIELDS,SEG_FIELDS


class AuditTests(unittest.TestCase):
    def test_only_positive_sightings_are_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td)
            def row(when,x=160,y=687):
                return dict(seen_at_utc=when,segment='c.pcapng',view_index=1,
                    server=125,x=x,y=y,type_code=3,subtype=310,
                    candidate_group_id='123',candidate_group_ambiguous='false',
                    entity_key=f'{x},{y}')
            append_csv(folder/'entity_sightings.csv',EVENT_FIELDS,[
                row('2026-11-06T12:00:00+00:00'),
                row('2026-11-06T12:02:00+00:00'),
                row('2026-11-06T12:00:30+00:00',x=200)])
            args=SimpleNamespace(server=125,x=160,y=687,radius=15,minutes=5)
            cutoff=parse_time('2026-11-06T12:01:00+00:00')
            evidence=compare_sightings(folder,args,cutoff)
            self.assertEqual(len(evidence),1)
            self.assertEqual(evidence[0]['before_sightings'],1)
            self.assertEqual(evidence[0]['after_sightings'],1)
            self.assertEqual(evidence[0]['assessment'],'seen_on_both_sides')

    def test_no_after_sighting_is_not_despawn(self):
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td)
            append_csv(folder/'entity_sightings.csv',EVENT_FIELDS,[
                dict(seen_at_utc='2026-11-06T12:00:00+00:00',
                     segment='c.pcapng',view_index=1,server=125,x=160,y=687,
                     type_code=3,subtype=310,candidate_group_id='x',
                     candidate_group_ambiguous='true',entity_key='k')])
            args=SimpleNamespace(server=125,x=160,y=687,radius=1,minutes=3)
            rows=compare_sightings(folder,args,parse_time('2026-11-06T12:01:00+00:00'))
            self.assertEqual(len(rows),1)
            self.assertIn('NOT_proof_of_despawn',rows[0]['assessment'])

    def test_manual_marker_records_level(self):
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td)
            args=SimpleNamespace(session=folder,label='defeated',server=125,
                x=160,y=687,visible_level=120,note='tested')
            mark(args)
            record=list(csv.DictReader((folder/'event_marks.csv').open(encoding='utf-8-sig')))[0]
            self.assertEqual(record['visible_level'],'120')
            other=SimpleNamespace(session=folder,server=125,x=160,y=687,cutoff=None)
            self.assertIsNotNone(cutoff_from_marks(folder,other))

    def test_no_messages_after_kill_must_be_visible(self):
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td)
            append_csv(folder/'segments.csv',SEG_FIELDS,[dict(
                file='first.pcapng',observed_at_utc='2026-11-06T12:00:00+00:00',
                incoming_packets=10,decoded_views=2,decoded_updates=1)])
            before,after=message_stats(folder,
                parse_time('2026-11-06T12:01:00+00:00'),5)
            self.assertEqual(before['views'],2)
            self.assertEqual(before['updates'],1)
            self.assertEqual(after['views']+after['updates'],0)


if __name__=='__main__':
    unittest.main()
