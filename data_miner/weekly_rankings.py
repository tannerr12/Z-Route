"""Step 7: switch from daily to This Week alliance rankings."""
import time

from scanner import adb, screenshot
from data_miner.target_locator import ask_vision, locate_text_button


def weekly_state(cfg, image):
    return ask_vision(cfg, image,
        "Inspect this Z-Route RANK screen. Return JSON with "
        "rank_screen boolean, selected_tab one of Today, This Week, unknown, "
        "my_alliance_checked boolean or null, and confidence 0..1. "
        "Only report a tab selected if its visual highlight is clear. "
        "Do not guess.")


def select_this_week(cfg):
    image = screenshot(cfg)
    state = weekly_state(cfg, image)
    confidence = state.get("confidence", 0)
    if state.get("rank_screen") is not True or isinstance(confidence, bool) or not isinstance(confidence, (int,float)) or confidence < .8:
        raise RuntimeError("Rankings screen not confirmed")
    if state.get("my_alliance_checked") is not True:
        raise RuntimeError("My Alliance must remain enabled")
    if state.get("selected_tab") != "This Week":
        x, y = locate_text_button(cfg, image, "This Week top tab",
                                  "RANK leaderboard with Today and This Week tabs", "top")
        adb(cfg, "shell", "input", "tap", str(x), str(y))
        time.sleep(.5)
        state = weekly_state(cfg, screenshot(cfg))
    if state.get("selected_tab") != "This Week" or state.get("my_alliance_checked") is not True:
        raise RuntimeError("This Week and My Alliance selections were not verified")
    return state
