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
        # OpenCV builds can return (N,1,4), (N,4), or a single line.
        line_rows = np.asarray(lines).reshape(-1, 4)
        for x1, y1, x2, y2 in line_rows:
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


def city_label_visible(image):
    """Fast local check for the HOME CITY's bottom-right Leave City button.

    This is much cheaper than a full-resolution Ollama vision request and
    distinguishes the unobstructed home city from full-screen sales offers.
    A failed OCR check is inconclusive (never grounds a tap).
    """
    height, width = image.shape[:2]
    region = image[int(height * .82):height, int(width * .70):width]
    if region.size == 0:
        return False
    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=2, fy=2,
                      interpolation=cv2.INTER_LINEAR)
    try:
        raw = pytesseract.image_to_string(
            gray, config="--psm 11", timeout=5).casefold()
    except (RuntimeError, OSError) as exc:
        print(f"Local Leave City OCR unavailable: {exc}; will use safe fallback",
              flush=True)
        return False
    words = " ".join(raw.split())
    return "leave city" in words


def leave_city_button_point(image):
    """Find the labeled Leave City button using local OCR, not Ollama.

    Return an emulator-screenshot pixel coordinate within the label if both
    words are spatially adjacent in the bottom-right city-navigation area.
    No blind tapping based on a fixed screen size or unsupported label.
    """
    height,width=image.shape[:2]
    x0,y0=int(width*.70),int(height*.82)
    region=image[y0:,x0:]
    if region.size==0:
        return None
    gray=cv2.cvtColor(region,cv2.COLOR_BGR2GRAY)
    gray=cv2.resize(gray,None,fx=2,fy=2,interpolation=cv2.INTER_LINEAR)
    try:
        info=pytesseract.image_to_data(
            gray,config="--psm 11",
            output_type=pytesseract.Output.DICT,timeout=5)
    except (RuntimeError,OSError) as exc:
        print(f"Leave City locator OCR unavailable: {exc}",flush=True)
        return None
    entries=[]
    for i,text in enumerate(info.get('text',[])):
        word=''.join(c for c in text.casefold() if c.isalpha())
        if not word:
            continue
        left=x0+float(info['left'][i])/2
        top=y0+float(info['top'][i])/2
        right=left+float(info['width'][i])/2
        bottom=top+float(info['height'][i])/2
        entries.append((word,left,top,right,bottom))
    candidates=[]
    for word,l,t,r,b in entries:
        if word=='leavecity':
            candidates.append((l,t,r,b))
        elif word=='leave':
            for other,l2,t2,r2,b2 in entries:
                if other!='city' or l2<l:
                    continue
                if abs((t+b)/2-(t2+b2)/2)>height*.032:
                    continue
                if l2-r>width*.08:
                    continue
                candidates.append((min(l,l2),min(t,t2),
                                   max(r,r2),max(b,b2)))
    if not candidates:
        return None
    # Prefer the lowest Leave City label if there is more than one.
    l,t,r,b=max(candidates,key=lambda bb:(bb[3],bb[2]))
    x,y=round((l+r)/2),round((t+b)/2)
    if not (width*.70<=x<width and height*.82<=y<height):
        return None
    return x,y


def run_ai_startup(cfg, max_actions=12, confidence_threshold=0.75,
                   allow_ai_fallback=True):
    """Reuse Player Activity's local login + popup flow; only ask AI as fallback.

    Crucially, don't call Ollama after an arbitrary number of promotions
    while another clearly identified promotion is still on-screen.
    """
    from data_miner.vision import classify_screen

    actions = 0
    promotions_closed = 0
    last_tap_image = None
    loading_deadline = time.monotonic() + 12
    while actions < max_actions:
        image = screenshot(cfg)
        if popup_visible(image):
            print("Login warning detected locally; tapping Confirm", flush=True)
            tap_scaled(cfg, image, CONFIRM_CENTER, REFERENCE_SIZE)
            actions += 1
            loading_deadline = time.monotonic() + 12
            time.sleep(0.8)
            continue

        # As soon as a city button is visible, hand off without loading a
        # costly multimodal model. This also protects decorative X icons
        # from ever being mistaken for the next promotion's close button.
        if promotions_closed >= 3 and city_label_visible(image):
            print("Leave City button confirmed by local OCR; city ready",
                  flush=True)
            return actions

        # Process the actual visible promo *before* using AI. There may be
        # four, five, or more sequential offers; never assume exactly three.
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
            loading_deadline = time.monotonic() + 12
            print("Waiting up to 3s for next overlay...", flush=True)
            wait_for_next_overlay(cfg)
            continue

        # No promotion close button is visible. Check the city locally once
        # before allowing a heavier AI-based fallback.
        if city_label_visible(image):
            print("Leave City button confirmed by local OCR; city ready",
                  flush=True)
            return actions

        if time.monotonic() < loading_deadline:
            print("No overlay yet; allowing transition to finish...",
                  flush=True)
            time.sleep(0.8)
            continue

        if not allow_ai_fallback:
            raise RuntimeError('Leave City label not verified after promotions. '
                               'AI fallback is disabled for the map scanner; '
                               'inspect saved screenshot before continuing')
        print("No verified promotion or Leave City label; using reduced-size "
              "Ollama classification fallback...", flush=True)
        height, width = image.shape[:2]
        target_height = min(height, 896)
        reduced = (cv2.resize(
            image, (max(1, round(width * target_height / height)),
                    target_height), interpolation=cv2.INTER_AREA)
                   if height > target_height else image)
        screen, confidence = classify_screen(cfg, reduced)
        print(f"Screen: {screen}, confidence: {confidence:.2f}", flush=True)
        if screen == "city" and confidence >= confidence_threshold:
            print("City ready; handing off to navigation", flush=True)
            return actions
        if screen == "promotion" and confidence >= confidence_threshold:
            raise RuntimeError(
                "Promotion detected but close button not verified; no tap performed"
            )
        if screen == "unknown":
            raise RuntimeError(
                "Unrecognized screen after local startup checks; "
                "saved state intact, no further taps performed"
            )
        raise RuntimeError(
            f"Expected city or verified promotion, got {screen} "
            f"({confidence:.2f}); no tap performed"
        )
    raise TimeoutError("Startup exceeded max_actions; stopped safely")


if __name__ == "__main__":
    config = load_config()
    print("Startup actions:", run_ai_startup(config))
