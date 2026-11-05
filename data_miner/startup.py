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


def promo_close_point(image):
    """Find a gold X using two intersecting diagonal strokes in known top-right ROIs."""
    height, width = image.shape[:2]
    # Earlier promotions and the Intelligence Weekly Card place X differently.
    centers = [
        (PROMO_CLOSE_CENTER[0] / PROMO_REFERENCE_SIZE[0],
         PROMO_CLOSE_CENTER[1] / PROMO_REFERENCE_SIZE[1]),
        (0.91, 0.11),
    ]
    for fx, fy in centers:
        x, y = round(fx * width), round(fy * height)
        half = max(14, round(width * 0.055))
        x0, y0 = max(0, x-half), max(0, y-half)
        crop = image[y0:min(height, y+half), x0:min(width, x+half)]
        if crop.size == 0:
            continue
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, (10, 25, 140), (45, 255, 255))
        lines = cv2.HoughLinesP(mask, 1, np.pi/180, threshold=9,
                                minLineLength=max(9, round(width*.018)),
                                maxLineGap=5)
        if lines is None:
            continue
        rising, falling = [], []
        for x1, y1, x2, y2 in lines[:, 0]:
            dx, dy = int(x2-x1), int(y2-y1)
            if abs(dx) < 6 or abs(dy) < 6:
                continue
            slope = dy/dx
            if .55 <= slope <= 1.7:
                rising.append(((x1+x2)/2, (y1+y2)/2))
            elif -1.7 <= slope <= -.55:
                falling.append(((x1+x2)/2, (y1+y2)/2))
        for px, py in rising:
            for qx, qy in falling:
                if abs(px-qx) <= half*.45 and abs(py-qy) <= half*.45:
                    return (round(x0+(px+qx)/2), round(y0+(py+qy)/2))
    return None


def promo_close_visible(image):
    return promo_close_point(image) is not None


def close_verified_promo(cfg, image):
    point = promo_close_point(image)
    if point is None:
        raise RuntimeError("Promotion X not locally verified; no tap performed")
    adb(cfg, "shell", "input", "tap", str(point[0]), str(point[1]))


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
        close_verified_promo(cfg, image)
        dismissed += 1
        time.sleep(wait_seconds)
    if promo_close_visible(screenshot(cfg)):
        raise TimeoutError("Promotional overlays remain after max_attempts")
    return dismissed


def wait_for_next_overlay(cfg, timeout=3.0, interval=0.3):
    """Poll for the next overlay before requesting expensive AI classification."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        image = screenshot(cfg)
        if popup_visible(image) or promo_close_visible(image):
            return image
        time.sleep(min(interval, max(0, deadline - time.monotonic())))
    return screenshot(cfg)


def run_ai_startup(cfg, max_actions=12, confidence_threshold=0.75):
    """Close verified overlays and transition to Alliance navigation at city."""
    from data_miner.vision import classify_screen

    actions = 0
    promotions_closed = 0
    last_tap_image = None
    while actions < max_actions:
        image = screenshot(cfg)
        if popup_visible(image):
            print("Login warning detected locally; tapping Confirm", flush=True)
            tap_scaled(cfg, image, CONFIRM_CENTER, REFERENCE_SIZE)
            actions += 1
            time.sleep(1)
            continue

        # A gold X alone does not prove a promotional overlay exists.
        # After several ads, explicitly verify city before any further taps.
        if promotions_closed >= 3:
            print("Checking for city after promotions...", flush=True)
            screen, confidence = classify_screen(cfg, image)
            print(f"Screen: {screen}, confidence: {confidence:.2f}", flush=True)
            if screen == "city" and confidence >= confidence_threshold:
                print("City ready; handing off to Alliance navigation", flush=True)
                return actions
            if screen != "promotion" or confidence < confidence_threshold:
                raise RuntimeError("Unable to verify city or promotion; no tap performed")

        point = promo_close_point(image)
        if point is not None:
            if last_tap_image is not None:
                before = cv2.resize(last_tap_image, (128, 128))
                after = cv2.resize(image, (128, 128))
                change = float(np.mean(cv2.absdiff(before, after)))
                if change < 3.0:
                    raise RuntimeError(
                        "Screen did not change after closing promotion; stopped repeated taps"
                    )
            print(f"Promotion X detected at {point}; closing", flush=True)
            last_tap_image = image.copy()
            close_verified_promo(cfg, image)
            promotions_closed += 1
            actions += 1
            print("Waiting up to 3s for next overlay...", flush=True)
            wait_for_next_overlay(cfg)
            continue

        print("Checking screen with Ollama...", flush=True)
        screen, confidence = classify_screen(cfg, image)
        print(f"Screen: {screen}, confidence: {confidence:.2f}", flush=True)
        if screen == "city" and confidence >= confidence_threshold:
            print("City ready; handing off to Alliance navigation", flush=True)
            return actions
        if screen == "promotion" and confidence >= confidence_threshold:
            raise RuntimeError("Promotion detected but X not verified; no tap performed")
        raise RuntimeError("Startup screen not recognized safely; no tap performed")
    raise TimeoutError("Startup exceeded max_actions; stopped safely")


if __name__ == "__main__":
    config = load_config()
    print("Startup actions:", run_ai_startup(config))
