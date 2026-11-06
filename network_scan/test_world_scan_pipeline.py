"""Offline tests for the no-Ollama login -> ads -> fixed Leave City workflow.

python -m unittest discover -s network_scan -p test_world_scan_pipeline.py
No ADB taps, Ollama requests or network captures are performed.
"""
from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import cv2
import numpy as np
import world_scan_pipeline as p


class WorldPipelineTests(unittest.TestCase):
    def setUp(self):
        self.image=np.zeros((192,108,3),dtype=np.uint8)
        self.map_image=np.full((192,108,3),200,dtype=np.uint8)
        self.roi=(80,2,106,27)

    def test_leave_city_scales_to_emulator_screen(self):
        self.assertEqual(p.leave_city_point(self.image),(98,183))
        self.assertEqual(p.leave_city_point(self.image,[80,180]),(80,180))
        with self.assertRaises(ValueError):
            p.leave_city_point(self.image,[120,190])
        with self.assertRaisesRegex(ValueError,'NOT in the bottom-right'):
            p.leave_city_point(self.image,[98,20])

    def test_local_template_requires_real_radar_reference(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'radar.png'
            self.assertEqual(p.radar_template_match(
                self.image,path,self.roi),(False,0.0))
            rng=np.random.default_rng(7)
            radar=rng.integers(0,256,(22,22),dtype=np.uint8)
            screen=np.zeros((192,108,3),dtype=np.uint8)
            screen[3:25,81:103,:]=radar[:,:,None]
            cv2.imwrite(str(path),radar)
            ready,score=p.radar_template_match(
                screen,path,self.roi,threshold=.86)
            self.assertTrue(ready)
            self.assertGreater(score,.95)
            unrelated=np.full_like(screen,80)
            ready,_=p.radar_template_match(
                unrelated,path,self.roi,threshold=.86)
            self.assertFalse(ready)

    def test_map_only_reuses_startup_and_never_calls_ollama(self):
        args=SimpleNamespace(
            roi=self.roi,max_startup_actions=12,
            map_tap=None,map_only=True,radar_template=None)
        with tempfile.TemporaryDirectory() as td:
            with (patch('data_miner.startup.run_ai_startup',return_value=5) as startup,
                  patch('data_miner.startup.popup_visible',return_value=False),
                  patch('data_miner.startup.promo_close_visible',return_value=False),
                  patch('data_miner.startup.city_label_visible',return_value=False),
                  patch('data_miner.target_locator.ask_vision',
                        side_effect=AssertionError('Ollama must not run')),
                  patch('data_miner.vision.classify_screen',
                        side_effect=AssertionError('Ollama must not run')),
                  patch.object(p,'read_screen',side_effect=[
                      self.image,self.image,self.map_image]),
                  patch.object(p,'save_screen'),
                  patch.object(p,'save_status') as status,
                  patch.object(p,'one_tap') as tap,
                  patch('time.sleep')):
                p.prepare_radar({},args,Path(td))
                startup.assert_called_once_with(
                    {},max_actions=12,allow_ai_fallback=False)
                tap.assert_called_once()
                self.assertEqual(tap.call_args.args[2],(98,183))
                self.assertTrue(any(x.args[1]=='map_only_complete'
                                    for x in status.call_args_list))

    def test_configured_old_map_point_in_top_right_is_ignored(self):
        args=SimpleNamespace(
            roi=self.roi,max_startup_actions=12,
            map_tap=None,map_only=True,radar_template=None)
        cfg={'ui':{'world_map':{'map_button_tap':[99,18]}}}
        with tempfile.TemporaryDirectory() as td:
            with (patch('data_miner.startup.run_ai_startup',return_value=0),
                  patch('data_miner.startup.popup_visible',return_value=False),
                  patch('data_miner.startup.promo_close_visible',return_value=False),
                  patch('data_miner.startup.city_label_visible',return_value=False),
                  patch.object(p,'read_screen',side_effect=[
                      self.image,self.image,self.map_image]),
                  patch.object(p,'save_screen'),
                  patch.object(p,'save_status'),
                  patch.object(p,'one_tap') as tap,
                  patch('time.sleep')):
                p.prepare_radar(cfg,args,Path(td))
                self.assertEqual(tap.call_args.args[2],(98,183))

    def test_explicit_top_right_map_tap_fails_closed(self):
        args=SimpleNamespace(
            roi=self.roi,max_startup_actions=12,
            map_tap=[99,18],map_only=True,radar_template=None)
        with tempfile.TemporaryDirectory() as td:
            with (patch('data_miner.startup.run_ai_startup',return_value=0),
                  patch('data_miner.startup.popup_visible',return_value=False),
                  patch('data_miner.startup.promo_close_visible',return_value=False),
                  patch.object(p,'read_screen',return_value=self.image),
                  patch.object(p,'save_screen'),
                  patch.object(p,'save_status'),
                  patch.object(p,'one_tap') as tap):
                with self.assertRaisesRegex(ValueError,'NOT in the bottom-right'):
                    p.prepare_radar({},args,Path(td))
                tap.assert_not_called()

    def test_popup_after_startup_never_taps_map(self):
        args=SimpleNamespace(
            roi=self.roi,max_startup_actions=12,
            map_tap=None,map_only=True,radar_template=None)
        with tempfile.TemporaryDirectory() as td:
            with (patch('data_miner.startup.run_ai_startup',return_value=5),
                  patch('data_miner.startup.popup_visible',return_value=True),
                  patch('data_miner.startup.promo_close_visible',return_value=False),
                  patch.object(p,'read_screen',return_value=self.image),
                  patch.object(p,'save_screen'),
                  patch.object(p,'save_status'),
                  patch.object(p,'one_tap') as tap):
                with self.assertRaisesRegex(RuntimeError,'Login/promo still visible'):
                    p.prepare_radar({},args,Path(td))
                tap.assert_not_called()

    def test_no_radar_reference_stops_before_zoom_or_scan(self):
        args=SimpleNamespace(
            roi=self.roi,max_startup_actions=12,
            map_tap=None,map_only=False,radar_template=None)
        with tempfile.TemporaryDirectory() as td:
            with (patch('data_miner.startup.run_ai_startup',return_value=5),
                  patch('data_miner.startup.popup_visible',return_value=False),
                  patch('data_miner.startup.promo_close_visible',return_value=False),
                  patch('data_miner.startup.city_label_visible',return_value=False),
                  patch.object(p,'read_screen',side_effect=[
                      self.image,self.image,self.map_image]),
                  patch.object(p,'save_screen'),
                  patch.object(p,'save_status'),
                  patch.object(p,'one_tap') as tap,
                  patch('time.sleep')):
                with self.assertRaisesRegex(RuntimeError,'calibrate the fixed radar'):
                    p.prepare_radar({},args,Path(td))
                tap.assert_called_once()


if __name__=='__main__':
    unittest.main()
