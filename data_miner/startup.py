"""Z-Route Data Miner startup: dismiss session warning and promotional offers.

Run: python -m data_miner.startup
Requires the existing config.json, adb, OpenCV and pytesseract setup.
"""
import time

import cv2
import pytesseract
import numpy as np

from scanner import load_config, screenshot, adb

REFERENCE_SIZE = (762, 1359)
CONFIRM_CENTER = (382, 765)
PROMO_REFERENCE_SIZE = (769, 1349)
PROMO_CLOSE_CENTER = (670, 182)


def tap_scaled(cfg, image, point, reference):
    height, width = image.shape[:2]
    x = round(point[0] * width / reference[0])
    y = round(point[1] * height / reference[1])
    adb(cfg, "shell", "input", "tap", str(x), str(y))


def popup_visible(image):
    """Recognize the known account warning across screen resolutions."""
    height, width = image.shape[:2]
    # The modal's text position varies by emulator scale.
    region = image[int(height * .27):int(height * .67),
                   int(width * .06):int(width * .94)]
    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=1.6, fy=1.6,
                      interpolation=cv2.INTER_LINEAR)
    variants = (gray, cv2.equalizeHist(gray))
    for variant in variants:
        text = pytesseract.image_to_string(variant, config="--psm 6").casefold()
        normalized = " ".join(text.split())
        if ("another device" in normalized and
            ("account" in normalized or "logged in" in normalized)):
            return True
    return False


def dismiss_login_popup(cfg, timeout=30, poll_interval=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        image = screenshot(cfg)
        if not popup_visible(image):
            return False
        tap_scaled(cfg, image, CONFIRM_CENTER, REFERENCE_SIZE)
        time.sleep(poll_interval)
        if not popup_visible(screenshot(cfg)):
            return True
    raise TimeoutError("Login popup still visible after retries")


def promo_close_visible(image):
    """Detect the light-gold X in the upper-right promotional overlay.

    Limit detection to the known close-button region to avoid tapping
    unrelated X icons elsewhere in the game.
    """
    height, width = image.shape[:2]
    x = round(PROMO_CLOSE_CENTER[0] * width / PROMO_REFERENCE_SIZE[0])
    y = round(PROMO_CLOSE_CENTER[1] * height / PROMO_REFERENCE_SIZE[1])
    half = max(12, round(width * 0.045))
    crop = image[max(0, y-half):min(height, y+half),
                 max(0, x-half):min(width, x+half)]
    if crop.size == 0:
        return False
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    # Gold/beige pixels in both diagonal strokes of the close icon.
    gold = cv2.inRange(hsv, (10, 35, 145), (40, 255, 255))
    n = gold.shape[0]
    if n < 10:
        return False
    yy, xx = np.indices(gold.shape)
    tolerance = max(3, round(n * 0.13))
    diagonal1 = np.abs(xx - yy) < tolerance
    diagonal2 = np.abs((xx + yy) - (n - 1)) < tolerance
    return (np.count_nonzero((gold > 0) & diagonal1) > 15 and
            np.count_nonzero((gold > 0) & diagonal2) > 15)


def dismiss_promotions(cfg, max_attempts=12, wait_seconds=0.5):
    dismissed = 0
    for _ in range(max_attempts):
        image = screenshot(cfg)
        if not promo_close_visible(image):
            # Check twice in case the next promotional overlay is loading.
            time.sleep(wait_seconds)
            if not promo_close_visible(screenshot(cfg)):
                return dismissed
            image = screenshot(cfg)
        tap_scaled(cfg, image, PROMO_CLOSE_CENTER, PROMO_REFERENCE_SIZE)
        dismissed += 1
        time.sleep(wait_seconds)
    if promo_close_visible(screenshot(cfg)):
        raise TimeoutError("Promotional overlays remain after max_attempts")
    return dismissed


def run_ai_startup(cfg, max_actions=12, confidence_threshold=0.75):
    """Fast local handling for known overlays; vision for unknown screens."""
    from data_miner.vision import classify_screen

    actions = 0
    while actions < max_actions:
        image = screenshot(cfg)
        # These are narrow, existing visual detectors; no Ollama call required.
        if popup_visible(image):
            print("Login warning detected locally; tapping Confirm", flush=True)
            tap_scaled(cfg, image, CONFIRM_CENTER, REFERENCE_SIZE)
            actions += 1
            time.sleep(0.8)
            continue
        if promo_close_visible(image):
            print("Promotion close icon detected locally; closing", flush=True)
            tap_scaled(cfg, image, PROMO_CLOSE_CENTER, PROMO_REFERENCE_SIZE)
            actions += 1
            time.sleep(0.8)
            continue

        # Unknown view: use the existing vision classifier, but never tap
        # based on AI alone without confirming the known visual target.
        print("Checking screen with Ollama (may take time)...", flush=True)
        try:
            screen, confidence = classify_screen(cfg, image)
        except TimeoutError as exc:
            raise RuntimeError(
                "Ollama screen classification timed out; stopped without tapping."
            ) from exc
        print(f"Screen: {screen}, confidence: {confidence:.2f}", flush=True)
        if confidence < confidence_threshold or screen == "unknown":
            raise RuntimeError("Uncertain screen: no tap performed")
        if screen == "city":
            return actions
        if screen == "other":
            raise RuntimeError("Unexpected game screen; no tap performed")
        if screen == "login_warning":
            if not popup_visible(image):
                raise RuntimeError("AI login classification not confirmed by OCR")
            tap_scaled(cfg, image, CONFIRM_CENTER, REFERENCE_SIZE)
        elif screen == "promotion":
            if not promo_close_visible(image):
                raise RuntimeError("AI promotion classification not confirmed by X detector")
            tap_scaled(cfg, image, PROMO_CLOSE_CENTER, PROMO_REFERENCE_SIZE)
        actions += 1
        time.sleep(0.5)
    raise TimeoutError("Startup exceeded max_actions; stopped safely")


if __name__ == "__main__":
    config = load_config()
    print("Startup actions:", run_ai_startup(config))
