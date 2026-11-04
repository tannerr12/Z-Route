"""Navigate back from weekly leaderboard after extraction."""
import time
from scanner import adb, screenshot
from data_miner.target_locator import locate_text_button, ask_vision


def back_to_competition(cfg):
    image = screenshot(cfg)
    x, y = locate_text_button(
        cfg, image, "gold back arrow button in bottom-left corner",
        "RANK screen with Today and This Week tabs", "bottom")
    if x > image.shape[1] * .3:
        raise RuntimeError("Back target not in bottom-left area")
    adb(cfg, "shell", "input", "tap", str(x), str(y))
    time.sleep(.5)
    result = ask_vision(cfg, screenshot(cfg),
        "Is this the Z-Route ALLIANCE COMPETITION page with Theme, Details, "
        "and Raid tabs? Return JSON with competition_screen boolean and "
        "confidence between 0 and 1.")
    conf = result.get("confidence", 0)
    if result.get("competition_screen") is not True or isinstance(conf,bool) or not isinstance(conf,(int,float)) or conf < .8:
        raise RuntimeError("Back tapped, but Alliance Competition destination not verified")
    return True
