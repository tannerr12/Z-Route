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
    height, width = image.shape[:2]
    region = image[int(height * .37):int(height * .52),
                   int(width * .10):int(width * .90)]
    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    text = pytesseract.image_to_string(gray).lower()
    return "account" in text and "another device" in text


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


def dismiss_promotions(cfg, max_attempts=12, wait_seconds=1.5):
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


if __name__ == "__main__":
    config = load_config()
    print("Login popup dismissed:", dismiss_login_popup(config))
    print("Promotional popups dismissed:", dismiss_promotions(config))
