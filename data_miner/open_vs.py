"""Step 3: open the VS event menu from the city screen."""
import time

from scanner import adb, load_config, screenshot
from data_miner.startup import run_ai_startup, tap_scaled
from data_miner.vision import classify_screen

CITY_REFERENCE_SIZE = (769, 1359)
VS_ICON_CENTER = (706, 648)


def open_vs(cfg, confidence_threshold=0.75):
    image = screenshot(cfg)
    screen, confidence = classify_screen(cfg, image)
    if screen != "city" or confidence < confidence_threshold:
        raise RuntimeError(f"Expected city screen before VS tap; got {screen} ({confidence:.2f})")
    tap_scaled(cfg, image, VS_ICON_CENTER, CITY_REFERENCE_SIZE)
    time.sleep(0.5)
    next_screen, next_confidence = classify_screen(cfg, screenshot(cfg))
    if next_screen == "city" and next_confidence >= confidence_threshold:
        raise RuntimeError("VS tap did not navigate away from city screen")
    if next_screen == "unknown" or next_confidence < confidence_threshold:
        raise RuntimeError("VS tap sent; resulting screen needs verification")
    return next_screen


if __name__ == "__main__":
    cfg = load_config()
    run_ai_startup(cfg)
    print("Screen after VS tap:", open_vs(cfg))
