"""Step 12: ensure Alliance Ranking > Donate > This Week is selected."""
import time

from scanner import adb, load_config, screenshot
from data_miner.target_locator import ask_vision, locate_text_button


def read_state(cfg, image):
    return ask_vision(cfg, image,
        "Inspect the ALLIANCE RANKING screen. Return JSON with "
        "alliance_ranking boolean, category one of Power,Kills,Donate,unknown, "
        "period one of Today,This Week,unknown, and confidence between 0 and 1. "
        "Read the selected highlighted tabs only; do not guess.")


def select_donate_this_week(cfg):
    for field, expected, target in (
        ("category", "Donate", "Donate tab in top row beside Power and Kills"),
        ("period", "This Week", "This Week tab in second row beside Today"),
    ):
        image = screenshot(cfg)
        state = read_state(cfg, image)
        conf = state.get("confidence", 0)
        if (state.get("alliance_ranking") is not True or isinstance(conf, bool)
                or not isinstance(conf, (int, float)) or not .8 <= conf <= 1):
            raise RuntimeError("Alliance Ranking screen not verified")
        if state.get(field) == expected:
            continue
        x, y = locate_text_button(cfg, image, target,
                                  "ALLIANCE RANKING page", "top")
        adb(cfg, "shell", "input", "tap", str(x), str(y))
        time.sleep(.5)
        state = read_state(cfg, screenshot(cfg))
        if state.get(field) != expected:
            raise RuntimeError(f"Could not verify selected {expected} tab")
    final = read_state(cfg, screenshot(cfg))
    if final.get("category") != "Donate" or final.get("period") != "This Week":
        raise RuntimeError("Donate / This Week final state not verified")
    return final


if __name__ == "__main__":
    print(select_donate_this_week(load_config()))
