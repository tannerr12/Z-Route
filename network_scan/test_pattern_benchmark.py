"""Offline tests for map-click route generation and fair replay.

Run: python -m unittest discover -s network_scan -p "test_pattern_benchmark.py"
No ADB clicks or network captures occur.
"""
import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from pattern_benchmark import PATTERNS, compare, ordered, targets


class PatternTests(unittest.TestCase):
    def setUp(self):
        self.points = targets(4, 5, [100, 100, 600, 400], .07)

    def test_every_pattern_visits_each_location_exactly_once(self):
        expected = {p['id'] for p in self.points}
        for pattern in PATTERNS:
            route = ordered(self.points, pattern)
            self.assertEqual(len(route), len(self.points), pattern)
            self.assertEqual({p['id'] for p in route}, expected, pattern)

    def test_points_stay_in_roi(self):
        for p in self.points:
            self.assertTrue(100 <= p['x'] <= 600)
            self.assertTrue(100 <= p['y'] <= 400)

    def test_snake_alternates_row_direction(self):
        route = ordered(self.points, 'snake')
        self.assertEqual([p['col'] for p in route[:5]], [0, 1, 2, 3, 4])
        self.assertEqual([p['col'] for p in route[5:10]], [4, 3, 2, 1, 0])

    def test_checkerboard_first_phase_alternates_parity(self):
        route = ordered(self.points, 'checkerboard')
        first_parity_one = next(i for i, p in enumerate(route)
                                if (p['row'] + p['col']) % 2 == 1)
        self.assertTrue(all((p['row'] + p['col']) % 2 == 0
                            for p in route[:first_parity_one]))

    def test_replay_has_equal_full_total_and_different_early_yields(self):
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            plan = folder / 'plan.json'
            pts = targets(2, 2, [0, 0, 200, 200])
            payload = dict(schema=1, targets=pts)
            plan.write_text(json.dumps(payload), encoding='utf-8')
            observations = [
                dict(target_id=p['id'], player_ids=ids, views=1, seconds=4)
                for p, ids in zip(pts, [['1', '2', '3'], ['3'], ['4'], ['5']])
            ]
            (folder / 'observations.json').write_text(json.dumps(dict(
                plan_sha256=hashlib.sha256(plan.read_bytes()).hexdigest(),
                entries=observations)), encoding='utf-8')
            compare(SimpleNamespace(session=folder, plan=plan))
            with (folder / 'comparison.csv').open(newline='', encoding='utf-8-sig') as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 5)
            self.assertTrue(all(row['available_unique_bases'] == '5' for row in rows))
            with (folder / 'comparison_progress.csv').open(
                    newline='', encoding='utf-8-sig') as f:
                progress = list(csv.DictReader(f))
            self.assertEqual(len(progress), 20)
            for pattern in ('snake', 'checkerboard', 'spiral', 'spread', 'greedy_oracle'):
                totals = [int(r['cumulative_unique']) for r in progress
                          if r['pattern'] == pattern]
                self.assertEqual(totals[-1], 5)
                self.assertEqual(totals, sorted(totals))


if __name__ == '__main__':
    unittest.main()
