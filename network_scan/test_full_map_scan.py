"""Offline checks for progressive minimap route/checkpoint logic.

Run: python -m unittest discover -s network_scan -p "test_full_map_scan.py"
No ADB actions, game-server requests, or packet captures occur.
"""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from full_map_scan import build, load_players, player_key, route, write_outputs


class FullMapTests(unittest.TestCase):
    def setUp(self):
        self.roi = [800, 25, 1060, 270]

    def test_center_first_route_with_no_duplicate_taps(self):
        points = route(self.roi, [4, 7, 10], .07, 8)
        self.assertGreaterEqual(len(points), 100)
        self.assertLessEqual(len(points), 165)
        self.assertEqual([p['number'] for p in points],
                         list(range(1, len(points)+1)))
        self.assertEqual(len({(p['tap_x'], p['tap_y']) for p in points}), len(points))
        self.assertTrue(all(800 <= p['tap_x'] <= 1060 and
                            25 <= p['tap_y'] <= 270 for p in points))
        first = [p for p in points if p['stage'] == 4][0]
        self.assertTrue(870 <= first['tap_x'] <= 990)
        self.assertTrue(85 <= first['tap_y'] <= 210)

    def test_adding_larger_stage_keeps_route_prefix(self):
        small = route(self.roi, [4, 7, 10], .07, 8)
        big = route(self.roi, [4, 7, 10, 13], .07, 8)
        self.assertEqual(big[:len(small)], small)
        self.assertGreater(len(big), len(small))

    def test_save_and_resume_with_safe_checkpoint_order(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            args = SimpleNamespace(out=folder, roi=self.roi,
                                   stages=[4, 7, 10], inset=.07,
                                   min_separation=8)
            plan = build(args)
            state = {'schema': 1, 'entries': [{
                'number': 1, 'stage': 4, 'target_id': plan[0]['target_id'],
                'tap_x': plan[0]['tap_x'], 'tap_y': plan[0]['tap_y'],
                'status': 'OK', 'attempts': 1, 'seconds': 4.2,
                'map_views': 1, 'observations': 1, 'new_ids': 1,
                'cumulative_ids': 1, 'centers': [[500, 500]],
                'capture': 'test.pcapng', 'incoming_bytes': 100,
                'decode_errors': 0, 'updated_at': '2026-11-06T00:00:00Z'
            }]}
            player = dict(server=125, x=518, y=415, username='test',
                          alliance_tag='TEST', alliance_name='Test',
                          base_level=27, player_id='123',
                          capture='test.pcapng', time_s='1')
            write_outputs(folder, state, {'125:123': player})
            self.assertEqual(len(load_players(folder / 'players.csv')), 1)
            self.assertEqual(len(json.loads((folder / 'checkpoint.json').
                                            read_text())['entries']), 1)
            args.stages = [4, 7, 10, 13]
            expanded = build(args)
            self.assertGreater(len(expanded), len(plan))
            args.roi = [700, 25, 1060, 270]
            with self.assertRaises(SystemExit):
                build(args)

    def test_player_identity(self):
        self.assertEqual(player_key({'server': 125, 'player_id': 123}), '125:123')
        self.assertIsNone(player_key({'server': 125, 'player_id': ''}))


if __name__ == '__main__':
    unittest.main()
