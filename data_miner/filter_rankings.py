"""Step 5: Filter the rankings screen to My Alliance, then Monday."""
import time

from scanner import adb, load_config, screenshot
from data_miner.open_rankings import open_rankings
from data_miner.startup import run_ai_startup
from data_miner.open_vs import open_vs
from data_miner.target_locator import ask_vision, locate_text_button


def ranking_state(cfg, image):
    result = ask_vision(cfg, image,
        "Inspect the Z-Route RANK screen. Return JSON with: "
        "rank_screen boolean; my_alliance_checked boolean or null if unclear; "
        "selected_day one of MON,TUE,WED,THUR,FRI,SAT,unknown; "
        "confidence between 0 and 1. Determine checkbox state from its "
        "visual checkmark or fill, not the text label. Do not guess.")
    return result


def require_rankings(state):
    conf = state.get("confidence", 0)
    if state.get("rank_screen") is not True or isinstance(conf, bool) or not isinstance(conf, (int, float)) or conf < .8 or conf > 1:
        raise RuntimeError("Rankings screen not confidently identified")


def tap_target(cfg, image, target, context, region):
    x, y = locate_text_button(cfg, image, target, context, region)
    adb(cfg, "shell", "input", "tap", str(x), str(y))
    time.sleep(.5)


def filter_monday_alliance(cfg):
    image = screenshot(cfg)
    state = ranking_state(cfg, image)
    require_rankings(state)
    if state.get("my_alliance_checked") is None:
        raise RuntimeError("Alliance checkbox state unclear; no tap performed")
    if state["my_alliance_checked"] is False:
        tap_target(cfg, image, "My Alliance checkbox at bottom-right",
                   "RANK screen with Today and This Week tabs", "bottom")
        image = screenshot(cfg)
        state = ranking_state(cfg, image)
        require_rankings(state)
        if state.get("my_alliance_checked") is not True:
            raise RuntimeError("My Alliance filter was not verified as enabled")
    if state.get("selected_day") != "MON":
        tap_target(cfg, image, "MON day tab at the top-left",
                   "RANK screen with weekday tabs", "top")
        image = screenshot(cfg)
        state = ranking_state(cfg, image)
        require_rankings(state)
    if state.get("selected_day") != "MON" or state.get("my_alliance_checked") is not True:
        raise RuntimeError("Monday + My Alliance selection could not be verified")
    return state


if __name__ == "__main__":
    cfg = load_config()
    run_ai_startup(cfg)
    open_vs(cfg)
    open_rankings(cfg)
    print("Rankings filters:", filter_monday_alliance(cfg))
