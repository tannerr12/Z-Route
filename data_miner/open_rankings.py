"""Navigate from Alliance Competition to its Rankings screen with vision."""
import time

from scanner import adb, load_config, screenshot
from data_miner.startup import run_ai_startup
from data_miner.open_vs import open_vs
from data_miner.targets import locate_vs_icon
from data_miner.vision import classify_screen
from data_miner.target_locator import locate_text_button


def open_rankings(cfg):
    image = screenshot(cfg)
    x, y = locate_text_button(
        cfg, image,
        target="RANKINGS button at the bottom of the Alliance Competition screen",
        context="ALLIANCE COMPETITION heading and Theme, Details, Raid tabs",
        region="bottom",
    )
    adb(cfg, "shell", "input", "tap", str(x), str(y))
    time.sleep(0.5)
    # Do not claim navigation succeeded merely because the tap was sent.
    after = screenshot(cfg)
    from data_miner.target_locator import check_rankings_screen
    if not check_rankings_screen(cfg, after):
        raise RuntimeError("Rankings tap sent but destination was not verified")
    return True


if __name__ == "__main__":
    cfg = load_config()
    run_ai_startup(cfg)
    open_vs(cfg)
    print("Rankings opened:", open_rankings(cfg))
