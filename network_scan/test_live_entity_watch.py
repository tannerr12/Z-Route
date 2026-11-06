"""Offline regression tests for live entity capture and visual matching.

Run: python -m unittest discover -s network_scan -p test_live_entity_watch.py
Uses synthetic entities and fake PCAP files; no ADB/Wireshark required.
"""
import csv
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from live_entity_watch import (candidate_key, decode_for_server, entity_key,
                               inspect_candidates, iter_entities, match, nearby,
                               process, read_csv, trail)


def entity(x,y,group=1793928700943,code=3):
    return dict(server=125,x=x,y=y,type_code=code,subtype=310,
                raw_object_field1=group,detail_scalars={'1':[310]},
                detail_text={})



def varint(v):
    out=[]
    while v>=128:
        out.append((v&127)|128);v>>=7
    out.append(v);return bytes(out)


def field(n,value):
    if isinstance(value,int):
        return varint(n<<3)+varint(value)
    return varint((n<<3)|2)+varint(len(value))+value


def encoded_update(server=125):
    location=field(1,server)+field(2,522)+field(3,415)+field(4,2000320207)
    objloc=field(1,server)+field(2,510)+field(3,400)
    obj=(field(1,1793928700943)+field(2,objloc)+field(3,3)
         +field(5,field(1,310)+field(2,1234))+field(999,4567))
    plain=(field(1,1)+field(2,34)+field(3,54)
           +field(4,location)+field(5,obj))
    salt,mask=19,206
    return bytes((((c+salt)&255)^mask) for c in plain)


class EntityWatchTests(unittest.TestCase):
    def test_small_encrypted_world_map_update_is_decoded(self):
        raw=encoded_update()
        root=decode_for_server(raw,125)
        self.assertTrue(any(n==5 and w==2 for n,w,v in root))
        with patch('live_entity_watch.application_messages',
                   return_value=iter([('WorldMapViewUpdateS2C',1.5,raw)])):
            decoded=list(iter_entities(Path('fake.pcapng'),server=125))
        self.assertEqual(len(decoded),1)
        kind,objects,players,fingerprint=decoded[0]
        self.assertEqual(kind,'delta')
        self.assertEqual(len(objects),1)
        self.assertEqual((objects[0]['x'],objects[0]['y']),(510,400))
        self.assertEqual(objects[0]['type_code'],3)
        self.assertEqual(len(fingerprint),64)

    def test_candidate_inspection_shows_nested_fields(self):
        from contextlib import redirect_stdout
        from io import StringIO
        with tempfile.TemporaryDirectory() as td:
            session=Path(td)
            headers=('entity_key','server','x','y','type_code','type_label','classification',
                     'subtype','candidate_group_id','candidate_group_ambiguous',
                     'first_seen_utc','last_seen_utc','last_capture','sightings',
                     'last_detail_scalars','last_detail_text')
            with (session/'latest_entities.csv').open('w',newline='',encoding='utf-8') as out:
                writer=csv.DictWriter(out,fieldnames=headers)
                writer.writeheader()
                writer.writerow(dict(entity_key='one',server=125,x=159,y=678,
                    type_code=5,type_label='Unclassified type 5',
                    classification='unknown',subtype=49,
                    candidate_group_id='1234',candidate_group_ambiguous='false',
                    first_seen_utc='2026-11-06T12:00:00+00:00',
                    last_seen_utc='2026-11-06T12:01:00+00:00',
                    last_capture='entity_00001.pcapng',sightings=3,
                    last_detail_scalars='{"1":[49]}',
                    last_detail_text='{}'))
            args=SimpleNamespace(session=session,server=125,x=160,y=687,
                                 radius=12,types=None,limit=30)
            buffer=StringIO()
            with redirect_stdout(buffer): inspect_candidates(args)
            output=buffer.getvalue()
            self.assertIn('type 5; subtype 49',output)
            self.assertIn('raw candidate ID: 1234',output)
            self.assertIn('{"1":[49]}',output)

    def test_shared_candidate_id_is_not_a_unique_entity_id(self):
        a,b=entity(492,409),entity(493,401)
        self.assertEqual(candidate_key(a),candidate_key(b))
        self.assertNotEqual(entity_key(a),entity_key(b))

    def test_same_view_multiple_coordinates_are_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)
            file=out/'segment1.pcapng'
            file.write_bytes(b'x'*100)
            latest,segments,cache={},[],{}
            fake=[('view',[entity(492,409),entity(493,401)],[], 'hash1')]
            with patch('live_entity_watch.iter_entities',return_value=iter(fake)), \
                 patch('live_entity_watch.traffic_stats',
                       return_value={'incoming_packets':10,'incoming_bytes':2000}):
                first=process(file,None,out,latest,segments,{},cache,None,limit=3,index=0)
            self.assertEqual(first['decoded_views'],1)
            self.assertEqual(first['new_entity_positions'],2)
            self.assertEqual(first['ambiguous_id_groups'],1)
            self.assertEqual(len(latest),2)
            self.assertTrue(all(x['candidate_group_ambiguous']=='true'
                                for x in latest.values()))
            file2=out/'segment2.pcapng'
            file2.write_bytes(b'x'*100)
            with patch('live_entity_watch.iter_entities',return_value=iter(fake)), \
                 patch('live_entity_watch.traffic_stats',
                       return_value={'incoming_packets':10,'incoming_bytes':2000}):
                second=process(file2,file,out,latest,segments,{},cache,None,
                               limit=3,index=1)
            # The same full map response in the adjacent joined window must
            # not create duplicate sightings.
            self.assertEqual(second['decoded_views'],0)
            self.assertEqual(second['new_entity_positions'],0)
            self.assertEqual(len(read_csv(out/'entity_sightings.csv')),2)
            file3=out/'segment3.pcapng'
            file3.write_bytes(b'x'*100)
            with patch('live_entity_watch.iter_entities',
                       return_value=iter([('view',[entity(494,402)],[],'hash2')])), \
                 patch('live_entity_watch.traffic_stats',
                       return_value={'incoming_packets':10,'incoming_bytes':2000}):
                third=process(file3,file2,out,latest,segments,{},cache,None,
                              limit=3,index=2)
            self.assertEqual(third['new_entity_positions'],1)
            self.assertEqual(len(latest),3)
            self.assertEqual(len(read_csv(out/'entity_sightings.csv')),3)

            nearargs=SimpleNamespace(session=out,server=125,x=492,y=409,
                         radius=0,types=None,within_minutes=10,limit=20)
            matches=nearby(nearargs)
            self.assertEqual(len(matches),1)
            self.assertEqual(matches[0][2]['x'],'492')
            markargs=SimpleNamespace(**vars(nearargs),label='Walker',
                                     code=3,screenshot=None,allow_nearby=False)
            match(markargs)
            saved=read_csv(out/'visual_matches.csv')
            self.assertEqual(len(saved),1)
            self.assertEqual(saved[0]['label'],'Walker')
            self.assertEqual(saved[0]['x'],'492')
            # Marking one coordinate MUST NOT silently reclassify every type 3.
            latest_again=read_csv(out/'latest_entities.csv')
            self.assertEqual(set(x['classification'] for x in latest_again),{'unknown'})
            trailargs=SimpleNamespace(session=out,server=125,code=3,
                                     group_id='1793928700943',limit=20)
            trail(trailargs)

    def test_missing_screenshot_or_ambiguous_coordinate_does_not_mark(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)
            file=out/'segment1.pcapng';file.write_bytes(b'x'*100)
            with patch('live_entity_watch.iter_entities',return_value=iter(
                    [('view',[entity(492,409,code=3),
                              entity(492,409,code=5)],[], 'hashx')])), \
                 patch('live_entity_watch.traffic_stats',
                       return_value={'incoming_packets':4,'incoming_bytes':100}):
                process(file,None,out,{},[],{}, {},None,index=0)
            args=SimpleNamespace(session=out,server=125,x=492,y=409,
                 radius=0,types=None,within_minutes=10,limit=10,
                 code=None,label='Walker',screenshot=None,allow_nearby=False)
            with self.assertRaises(SystemExit):
                match(args)
            self.assertFalse((out/'visual_matches.csv').is_file())


if __name__=='__main__':
    unittest.main()
