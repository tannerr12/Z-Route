"""Z-Route Data Miner startup: dismiss the known account-session popup.

Run: python -m data_miner.startup
Requires the existing config.json, adb, OpenCV and pytesseract setup.
"""
import time

import cv2
import pytesseract

from scanner import load_config, screenshot, adb

POPUP_TEXT = "this account is logged in on another device"
REFERENCE_SIZE = (762, 1359)
CONFIRM_CENTER = (382, 765)


def popup_visible(image):
    height, width = image.shape[:2]
    # OCR the middle of the screen where the warning appears.
    region = image[int(height * .37):int(height * .52),
                   int(width * .10):int(width * .90)]
    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    text = pytesseract.image_to_string(gray).lower()
    return ("account" in text and "another device" in text)


def dismiss_login_popup(cfg, timeout=30, poll_interval=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        image = screenshot(cfg)
        if not popup_visible(image):
            return False  # Popup absent; don't click arbitrary UI.
        height, width = image.shape[:2]
        x = round(CONFIRM_CENTER[0] * width / REFERENCE_SIZE[0])
        y = round(CONFIRM_CENTER[1] * height / REFERENCE_SIZE[1])
        adb(cfg, "shell", "input", "tap", str(x), str(y))
        time.sleep(poll_interval)
        if not popup_visible(screenshot(cfg)):
            return True
    raise TimeoutError("Login popup still visible after retries")


if __name__ == "__main__":
    config = load_config()
    print("Dismissed login popup" if dismiss_login_popup(config)
          else "Login popup not present")
