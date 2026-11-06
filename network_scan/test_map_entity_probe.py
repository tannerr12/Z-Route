"""Offline checks for map type and status field inventory.

Run: python -m unittest discover -s network_scan -p test_map_entity_probe.py
No Wireshark/ADB or network calls.
"""
import unittest
from map_entity_probe import (signed64, timestamp_utc, parse_object,
                              world_key, status_record, classify)
from zroute_map_decoder import protobuf_fields


def varint(value):
    out=[]
    while value>127:
        out.append((value&127)|128)
        value>>=7
    out.append(value)
    return bytes(out)


def field(num,value):
    if isinstance(value,int):
        return varint(num*8)+varint(value)
    return varint(num*8+2)+varint(len(value))+value


class MapEntityTests(unittest.TestCase):
    def test_signed_negative_object_type(self):
        self.assertEqual(signed64((1<<64)-303),-303)
        self.assertEqual(signed64(9917),9917)

    def test_unknown_type_is_not_claimed_to_be_walker(self):
        self.assertEqual(classify(3,{})[1],'unknown')
        self.assertEqual(classify(5,{})[1],'unknown')
        self.assertEqual(classify(3,{3:('Walker',False)})[1],
                         'unverified_manual_label')
        self.assertEqual(classify(3,{3:('Walker',True)})[1],
                         'visually_verified')

    def test_parse_npc_and_coordinates(self):
        loc=field(1,125)+field(2,405)+field(3,551)
        extra=field(1,308)+field(2,205400)
        obj=field(1,123)+field(2,loc)+field(3,3)+field(5,extra)+field(999,12)
        result=parse_object(obj)
        self.assertEqual(result['server'],125)
        self.assertEqual((result['x'],result['y']),(405,551))
        self.assertEqual(result['type_code'],3)
        self.assertEqual(result['subtype'],308)
        self.assertEqual(result['detail_scalars']['2'],[205400])
        self.assertEqual(world_key(result),world_key(result))

    def test_player_status_never_assumes_no_shield(self):
        loc=field(1,125)+field(2,518)+field(3,415)
        extra=(field(1,999999)+field(2,27)+field(4,b'TestPlayer')
               +field(6,b'D3AD')+field(15,2)+field(18,1793932531824))
        obj=field(1,123)+field(2,loc)+field(3,1)+field(4,extra)
        entity=parse_object(obj)
        state=status_record(entity,'capture.pcapng','2026-11-06T02:00:00Z')
        self.assertEqual(state['player_id'],999999)
        self.assertEqual(state['status_15'],2)
        self.assertTrue(state['status_18_utc'].startswith('2026-11'))
        self.assertEqual(state['shield_status'],'unverified')


if __name__=='__main__':
    unittest.main()
