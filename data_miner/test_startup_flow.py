"""Regression tests: never invoke heavyweight AI while more popups can close.

Run from repository root:
 python -m unittest discover -s data_miner -p test_startup_flow.py
"""
import unittest
from unittest.mock import patch
import numpy as np

from data_miner import startup


class StartupFlowTests(unittest.TestCase):

    def test_login_and_four_ads_close_without_ollama(self):
        # Login warning, four sequential offers, then unobstructed home city.
        frames=[np.full((120,90,3),i*30,dtype=np.uint8)
                for i in range(10)]
        with (patch.object(startup,'screenshot',side_effect=frames),
              patch.object(startup,'popup_visible',
                           side_effect=[True,False,False,False,False,False]),
              patch.object(startup,'city_label_visible',
                           side_effect=[False,False,False,False,False,False,False,False,True]),
              patch.object(startup,'leave_city_button_point',return_value=None),
              patch.object(startup,'promotion_content_visible',return_value=True),
              patch.object(startup,'promo_close_point',
                           side_effect=[(70,12)]*8),
              patch.object(startup,'close_verified_promo') as close,
              patch.object(startup,'tap_scaled') as confirm,
              patch.object(startup,'wait_for_next_overlay'),
              patch('data_miner.vision.classify_screen') as expensive,
              patch.object(startup.time,'sleep')):
            actions=startup.run_ai_startup({},max_actions=12)
            self.assertEqual(actions,5)
            confirm.assert_called_once()
            self.assertEqual(close.call_count,4)
            expensive.assert_not_called()

    def test_city_with_top_right_decoration_does_not_close_fake_promo(self):
        frame=np.zeros((120,90,3),dtype=np.uint8)
        with (patch.object(startup,'screenshot',return_value=frame),
              patch.object(startup,'popup_visible',return_value=False),
              patch.object(startup,'city_label_visible',return_value=True),
              patch.object(startup,'promo_close_point',
                           return_value=(83,8)) as promo,
              patch.object(startup,'close_verified_promo') as close,
              patch('data_miner.vision.classify_screen') as expensive):
            self.assertEqual(startup.run_ai_startup({},allow_ai_fallback=False),0)
            promo.assert_not_called()
            close.assert_not_called()
            expensive.assert_not_called()

    def test_city_locator_blocks_false_promo_close_when_label_ocr_misses(self):
        frame=np.zeros((120,90,3),dtype=np.uint8)
        with (patch.object(startup,'screenshot',return_value=frame),
              patch.object(startup,'popup_visible',return_value=False),
              patch.object(startup,'city_label_visible',return_value=False),
              patch.object(startup,'leave_city_button_point',return_value=(85,112)),
              patch.object(startup,'promo_close_point',
                           return_value=(83,8)),
              patch.object(startup,'close_verified_promo') as close,
              patch('data_miner.vision.classify_screen') as expensive):
            self.assertEqual(startup.run_ai_startup({},allow_ai_fallback=False),0)
            close.assert_not_called()
            expensive.assert_not_called()

    def test_second_frame_city_check_blocks_false_promo_close(self):
        frame=np.zeros((120,90,3),dtype=np.uint8)
        with (patch.object(startup,'screenshot',return_value=frame),
              patch.object(startup,'popup_visible',return_value=False),
              patch.object(startup,'city_label_visible',
                           side_effect=[False,False,True]),
              patch.object(startup,'leave_city_button_point',return_value=None),
              patch.object(startup,'promo_close_point',return_value=(83,8)),
              patch.object(startup,'close_verified_promo') as close,
              patch.object(startup.time,'sleep')):
            self.assertEqual(startup.run_ai_startup({},allow_ai_fallback=False),0)
            close.assert_not_called()

    def test_decorative_x_not_enough_even_when_ocr_misses_city(self):
        frame=np.zeros((120,90,3),dtype=np.uint8)
        with (patch.object(startup,'screenshot',return_value=frame),
              patch.object(startup,'popup_visible',return_value=False),
              patch.object(startup,'city_label_visible',return_value=False),
              patch.object(startup,'leave_city_button_point',return_value=None),
              patch.object(startup,'promo_close_point',return_value=(83,8)),
              patch.object(startup,'promotion_content_visible',return_value=False),
              patch.object(startup,'close_verified_promo') as close,
              patch.object(startup.time,'sleep')):
            with self.assertRaisesRegex(RuntimeError,'Ambiguous top-right X'):
                startup.run_ai_startup({},allow_ai_fallback=False)
            close.assert_not_called()

    def test_city_detected_without_promotions_needs_no_ai(self):
        frame=np.zeros((120,90,3),dtype=np.uint8)
        with (patch.object(startup,'screenshot',return_value=frame),
              patch.object(startup,'popup_visible',return_value=False),
              patch.object(startup,'promo_close_point',return_value=None),
              patch.object(startup,'city_label_visible',return_value=True),
              patch('data_miner.vision.classify_screen') as expensive):
            self.assertEqual(startup.run_ai_startup({}),0)
            expensive.assert_not_called()

    def test_city_label_not_confirmed_does_not_claim_success(self):
        frame=np.zeros((120,90,3),dtype=np.uint8)
        with (patch.object(startup,'screenshot',return_value=frame),
              patch.object(startup,'popup_visible',return_value=False),
              patch.object(startup,'promo_close_point',return_value=None),
              patch.object(startup,'city_label_visible',return_value=False),
              patch('data_miner.vision.classify_screen',
                    return_value=('other',.99)) as expensive,
              patch.object(startup.time,'monotonic',side_effect=[1000.0,1013.0]),
              patch.object(startup.time,'sleep')):
            with self.assertRaisesRegex(RuntimeError,'Expected city'):
                startup.run_ai_startup({})
            expensive.assert_called_once()


if __name__=='__main__':
    unittest.main()
