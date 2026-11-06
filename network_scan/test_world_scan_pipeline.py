"""Offline safety tests for the login-to-radar end-to-end pipeline.

Run from repository root:
 python -m unittest discover -s network_scan -p test_world_scan_pipeline.py
No emulator, Ollama or game-server connection is required.
"""
from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import world_scan_pipeline as p


class WorldPipelineTests(unittest.TestCase):
    def setUp(self):
        self.image=SimpleNamespace(shape=(1920,1080,3))
        self.roi=(800,25,1060,270)

    def test_radar_must_fit_top_right_roi(self):
        self.assertTrue(p.radar_box_valid([820,35,1010,240],self.image,self.roi))
        self.assertFalse(p.radar_box_valid([100,35,300,240],self.image,self.roi))
        self.assertFalse(p.radar_box_valid([820,35,822,36],self.image,self.roi))
        self.assertFalse(p.radar_box_valid([700,35,770,240],self.image,self.roi))
        self.assertFalse(p.radar_box_valid([820,35,1100,3000],self.image,self.roi))
        self.assertFalse(p.radar_box_valid(None,self.image,self.roi))

    def test_coordinates_use_emulator_pixels(self):
        self.assertEqual(p.coordinate([500,750],self.image),(500,750))
        with self.assertRaises(ValueError):p.coordinate([1080,750],self.image)
        with self.assertRaises(ValueError):p.coordinate([500,1920],self.image)
        with self.assertRaises(ValueError):p.coordinate([500.2,750],self.image)

    def test_confidence_requires_real_boolean_and_threshold(self):
        self.assertTrue(p.confidence({'world_map':True,'confidence':.92},'world_map'))
        self.assertFalse(p.confidence({'world_map':1,'confidence':.99},'world_map'))
        self.assertFalse(p.confidence({'world_map':True,'confidence':.6},'world_map'))
        self.assertFalse(p.confidence({'world_map':True,'confidence':True},'world_map'))

    def test_existing_radar_needs_two_verifications_no_taps(self):
        cfg={}
        args=SimpleNamespace(roi=self.roi,max_startup_actions=12,max_zoom_actions=5)
        with tempfile.TemporaryDirectory() as td:
            with (patch('data_miner.startup.popup_visible',return_value=False),
                  patch('data_miner.startup.promo_close_visible',return_value=False),
                  patch('data_miner.startup.city_label_visible',return_value=False),
                  patch.object(p,'read_screen',return_value=self.image),
                  patch.object(p,'save_screen'),
                  patch.object(p,'save_status') as status,
                  patch.object(p,'vision_world',return_value=(True,True,{})) as vision,
                  patch.object(p,'one_tap') as tap,
                  patch.object(p,'locate_city_map') as map_loc,
                  patch.object(p,'locate_zoom_out') as zoom_loc):
                p.prepare_radar(cfg,args,Path(td))
                self.assertEqual(vision.call_count,2)
                tap.assert_not_called()
                map_loc.assert_not_called()
                zoom_loc.assert_not_called()
                self.assertTrue(any(c.args[1]=='radar_verified' for c in status.call_args_list))

    def test_login_warning_uses_existing_player_activity_startup_before_world_ai(self):
        cfg={}
        args=SimpleNamespace(roi=self.roi,max_startup_actions=12,
                             max_zoom_actions=5,map_tap=[930,1850])
        events=[]
        with tempfile.TemporaryDirectory() as td:
            with (patch('data_miner.startup.popup_visible',return_value=True),
                  patch('data_miner.startup.run_ai_startup',
                        side_effect=lambda *a,**kw:events.append('startup') or 4) as startup,
                  patch('data_miner.startup.city_label_visible',return_value=True),
                  patch('data_miner.vision.classify_screen',return_value=('city',.99)) as ai,
                  patch.object(p,'read_screen',return_value=self.image),
                  patch.object(p,'save_screen'),
                  patch.object(p,'save_status') as status,
                  patch.object(p,'one_tap'),
                  patch.object(p,'vision_world',
                        side_effect=lambda *a,**kw:events.append('vision') or (True,True,{})) as vision,
                  patch.object(p,'verify_world_after_map',return_value=(self.image,True)),
                  patch('time.sleep')):
                p.prepare_radar(cfg,args,Path(td))
                self.assertEqual(events,['startup','vision'],
                                 'Login handler must run before any world-map AI')
                startup.assert_called_once_with(cfg,max_actions=12)
                ai.assert_not_called()
                self.assertEqual(vision.call_count,1)
                self.assertTrue(any(c.args[1]=='login_warning_detected'
                                    for c in status.call_args_list))

    def test_unverified_radar_causes_safe_stop_before_scanner(self):
        cfg={}
        args=SimpleNamespace(roi=self.roi,max_startup_actions=12,max_zoom_actions=1,
                             zoom_tap=None,zoom_keyevent=None)
        with tempfile.TemporaryDirectory() as td:
            with (patch('data_miner.startup.popup_visible',return_value=False),
                  patch('data_miner.startup.promo_close_visible',return_value=False),
                  patch('data_miner.startup.city_label_visible',return_value=False),
                  patch.object(p,'read_screen',return_value=self.image),
                  patch.object(p,'save_screen'),
                  patch.object(p,'save_status'),
                  patch.object(p,'vision_world',return_value=(True,False,{})),
                  patch.object(p,'locate_zoom_out',side_effect=RuntimeError('not visible')),
                  patch.object(p,'one_tap') as tap):
                with self.assertRaisesRegex(RuntimeError,'Zoom-out control could not be verified'):
                    p.prepare_radar(cfg,args,Path(td))
                tap.assert_not_called()


if __name__=='__main__':
    unittest.main()
