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
            with self.assertRaisesRegex(FileNotFoundError,'Radar reference PNG not found'):
                p.radar_template_match(self.image,path,self.roi)
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

    def test_map_only_ignores_world_map_gold_x_false_positive(self):
        args=SimpleNamespace(
            roi=self.roi,max_startup_actions=12,map_tap=None,
            map_only=True,radar_template=None)
        with tempfile.TemporaryDirectory() as td:
            with (patch('data_miner.startup.run_ai_startup',return_value=4),
                  patch('data_miner.startup.popup_visible',return_value=False),
                  patch('data_miner.startup.promo_close_visible',
                        return_value=True) as promo,
                  patch('data_miner.startup.city_label_visible',return_value=True),
                  patch.object(p,'read_screen',
                               side_effect=[self.image,self.image,self.map_image]),
                  patch.object(p,'save_screen'),
                  patch.object(p,'save_status') as status,
                  patch.object(p,'one_tap') as tap,
                  patch('time.sleep')):
                p.prepare_radar({},args,Path(td))
                tap.assert_called_once()
                self.assertTrue(any(c.args[1]=='map_only_complete'
                                    for c in status.call_args_list))
                # After Leave City, the startup promo detector must never
                # be trusted to classify the world map.
                self.assertEqual(promo.call_count,1)

    def test_zoom_only_calls_one_two_second_hold(self):
        args=SimpleNamespace(zoom_steps=1,zoom_delay=.6,zoom_hold=2.0)
        with tempfile.TemporaryDirectory() as td:
            with (patch('data_miner.startup.popup_visible',return_value=False),
                  patch('bluestacks_zoom.zoom_out_ctrl_minus') as zoom,
                  patch.object(p,'read_screen',side_effect=[
                      self.image,self.map_image]),
                  patch.object(p,'save_screen'),
                  patch.object(p,'save_status') as status,
                  patch('time.sleep')):
                p.zoom_probe({},args,Path(td))
                zoom.assert_called_once_with(2.0)
                self.assertTrue(any(c.args[1]=='zoom_probe_complete'
                                    for c in status.call_args_list))

    def test_one_hold_even_when_screen_change_is_small(self):
        args=SimpleNamespace(zoom_steps=1,zoom_delay=.6,zoom_hold=3.0)
        with tempfile.TemporaryDirectory() as td:
            with (patch('data_miner.startup.popup_visible',return_value=False),
                  patch('bluestacks_zoom.zoom_out_ctrl_minus') as zoom,
                  patch.object(p,'read_screen',side_effect=[
                      self.image,self.image]),
                  patch.object(p,'save_screen'),
                  patch.object(p,'save_status'),
                  patch('time.sleep')):
                p.zoom_probe({},args,Path(td))
                zoom.assert_called_once_with(3.0)

    def test_zoom_hold_validation(self):
        from bluestacks_zoom import zoom_out_ctrl_minus
        for hold in (0.16,1.9,5.1,True,'2'):
            with self.subTest(hold=hold):
                with self.assertRaises(ValueError):
                    zoom_out_ctrl_minus(hold)

    def test_multiple_hold_count_rejected(self):
        args=SimpleNamespace(zoom_steps=2,zoom_delay=.6,zoom_hold=2.0)
        with tempfile.TemporaryDirectory() as td:
            with (patch('data_miner.startup.popup_visible',return_value=False),
                  patch('bluestacks_zoom.zoom_out_ctrl_minus') as zoom,
                  patch.object(p,'read_screen',return_value=self.image),
                  patch.object(p,'save_screen'),
                  patch.object(p,'save_status')):
                with self.assertRaisesRegex(ValueError,'exactly one held'):
                    p.zoom_probe({},args,Path(td))
                zoom.assert_not_called()

    def test_zoom_only_does_not_send_key_on_login_popup(self):
        args=SimpleNamespace(zoom_steps=1,zoom_delay=.6,zoom_hold=2.0)
        with tempfile.TemporaryDirectory() as td:
            with (patch('data_miner.startup.popup_visible',return_value=True),
                  patch('bluestacks_zoom.zoom_out_ctrl_minus') as zoom,
                  patch.object(p,'read_screen',return_value=self.image),
                  patch.object(p,'save_screen'),
                  patch.object(p,'save_status')):
                with self.assertRaisesRegex(RuntimeError,'Login warning'):
                    p.zoom_probe({},args,Path(td))
                zoom.assert_not_called()

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

    def test_no_radar_template_required_after_one_zoom(self):
        args=SimpleNamespace(
            roi=self.roi,max_startup_actions=12,map_tap=None,map_only=False,
            radar_template=None,zoom_method='bluestacks',zoom_hold=2.0,
            zoom_delay=.6)
        with tempfile.TemporaryDirectory() as td:
            with (patch('data_miner.startup.run_ai_startup',return_value=5),
                  patch('data_miner.startup.popup_visible',return_value=False),
                  patch('data_miner.startup.promo_close_visible',return_value=False),
                  patch('data_miner.startup.city_label_visible',return_value=False),
                  patch('bluestacks_zoom.zoom_out_ctrl_minus') as zoom,
                  patch.object(p,'radar_template_match',
                               side_effect=AssertionError('Radar matching must not run')),
                  patch.object(p,'read_screen',side_effect=[
                      self.image,self.image,self.map_image,self.map_image]),
                  patch.object(p,'save_screen'),
                  patch.object(p,'save_status') as status,
                  patch.object(p,'one_tap') as tap,
                  patch('time.sleep')):
                p.prepare_radar({},args,Path(td))
                zoom.assert_called_once_with(2.0)
                tap.assert_called_once()
                self.assertTrue(any(x.args[1]=='zoom_complete_no_radar_check'
                                    for x in status.call_args_list))


if __name__=='__main__':
    unittest.main()
