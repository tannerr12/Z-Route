"""Step 10: open Alliance from the city screen using vision-detected target."""
import time

from scanner import adb, load_config, screenshot
from data_miner.vision import classify_screen
from data_miner.target_locator import locate_text_button, ask_vision


def open_alliance(cfg):
    image = screenshot(cfg)
    screen, confidence = classify_screen(cfg, image)
    if screen != "city" or confidence < .8:
        raise RuntimeError(f"Expected city view, got {screen} ({confidence:.2f})")
    x, y = locate_text_button(
        cfg, image,
        "Alliance button with gold crossed swords icon and Alliance label",
        "Z-Route town view with right-side vertical menu", "any")
    h, w = image.shape[:2]
    if x < w * .65 or y < h * .55:
        raise RuntimeError("Detected Alliance target outside expected right-side lower menu")
    adb(cfg, "shell", "input", "tap", str(x), str(y))
    time.sleep(.5)
    result = ask_vision(cfg, screenshot(cfg),
        "Is this the Z-Route Alliance menu or Alliance home screen, rather than "
        "the city view? Return JSON with alliance_screen boolean and confidence 0..1.")
    conf = result.get("confidence", 0)
    if result.get("alliance_screen") is not True or isinstance(conf, bool) or not isinstance(conf, (int,float)) or not .8 <= conf <= 1:
        raise RuntimeError("Alliance tap sent, but Alliance menu not verified")
    return True


if __name__ == "__main__":
    print("Alliance opened:", open_alliance(load_config()))
