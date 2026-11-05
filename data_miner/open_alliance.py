"""Step 10: open Alliance from the city screen using vision-detected target."""
import time

from scanner import adb, load_config, screenshot
import cv2
import pytesseract
from data_miner.vision import classify_screen
from data_miner.target_locator import locate_text_button, ask_vision


def open_alliance(cfg):
    image = screenshot(cfg)
    screen, confidence = classify_screen(cfg, image)
    if screen != "city" or confidence < .8:
        raise RuntimeError(f"Expected city view, got {screen} ({confidence:.2f})")
    h, w = image.shape[:2]
    # The Alliance button is in the lower-right navigation column.
    # Verify its printed label locally before tapping a calibrated position.
    x0, x1 = int(w * .85), w
    y0, y1 = int(h * .62), int(h * .78)
    region = image[y0:y1, x0:x1]
    enlarged = cv2.resize(region, None, fx=2, fy=2,
                           interpolation=cv2.INTER_CUBIC)
    words = pytesseract.image_to_data(
        enlarged, config="--psm 11",
        output_type=pytesseract.Output.DICT)
    matches = []
    for i, word in enumerate(words["text"]):
        if word.strip().casefold() == "alliance":
            left = words["left"][i]
            top = words["top"][i]
            width = words["width"][i]
            height = words["height"][i]
            matches.append((x0 + (left + width/2)/2,
                            y0 + (top + height/2)/2))
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected one Alliance label in lower-right menu, found {len(matches)}; "
            "no tap performed"
        )
    label_x, label_y = matches[0]
    # Tap above the detected label, within the same navigation tile.
    x, y = round(label_x), round(label_y - h * .035)
    print(f"Alliance label at ({label_x:.0f}, {label_y:.0f}); "
          f"tapping ({x}, {y}) on {w}x{h}", flush=True)
    if not (w*.85 <= x < w and h*.62 <= y < h*.78):
        raise RuntimeError("Alliance tap outside lower-right navigation; no tap performed")
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
