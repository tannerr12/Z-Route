"""Step 11: open Member Rankings from the Alliance home screen."""
import time

from scanner import adb, load_config, screenshot
from data_miner.target_locator import ask_vision, locate_text_button


def open_member_rankings(cfg):
    image = screenshot(cfg)
    state = ask_vision(cfg, image,
        "Is this the Z-Route ALLIANCE home page showing the alliance banner, "
        "Alliance War, Members, Alliance Research and Member Rankings buttons? "
        "Return JSON with alliance_home boolean and confidence 0..1.")
    confidence = state.get("confidence", 0)
    if (state.get("alliance_home") is not True or isinstance(confidence, bool)
            or not isinstance(confidence, (int, float)) or confidence < .8
            or confidence > 1):
        raise RuntimeError("Alliance home screen not verified")
    x, y = locate_text_button(
        cfg, image,
        "Member Rankings button with gold medal icon in the left column",
        "ALLIANCE home page; distinct from Members button", "any")
    h, w = image.shape[:2]
    if x > w * .55 or not h * .45 < y < h * .85:
        raise RuntimeError("Member Rankings target outside expected menu area")
    adb(cfg, "shell", "input", "tap", str(x), str(y))
    time.sleep(.5)
    result = ask_vision(cfg, screenshot(cfg),
        "Is this the Member Rankings page showing an alliance member ranking "
        "list or its ranking categories, rather than the ALLIANCE home page? "
        "Return JSON with member_rankings_screen boolean and confidence 0..1.")
    conf = result.get("confidence", 0)
    if (result.get("member_rankings_screen") is not True
            or isinstance(conf, bool) or not isinstance(conf, (int, float))
            or not .8 <= conf <= 1):
        raise RuntimeError("Member Rankings navigation not verified")
    return True


if __name__ == "__main__":
    print("Member Rankings opened:", open_member_rankings(load_config()))
