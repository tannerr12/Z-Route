"""Reusable Ollama locator for labeled buttons and screen verification."""
import base64
import json
import urllib.request
import cv2


def ask_vision(cfg, image, instruction):
    h, w = image.shape[:2]
    ok, png = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError("Screenshot encoding failed")
    payload = {
        "model": cfg.get("ollama", {}).get("model", "qwen2.5vl:3b"),
        "stream": False,
        "format": "json",
        "options": {"temperature": 0},
        "messages": [{"role": "user", "content": instruction +
            f" Image size: {w}x{h} pixels. Return only valid JSON.",
            "images": [base64.b64encode(png.tobytes()).decode("ascii")]}]
    }
    req = urllib.request.Request(
        "http://127.0.0.1:11434/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as response:
        result = json.load(response)
    if not result.get("done"):
        raise RuntimeError("Incomplete Ollama response")
    return json.loads(result["message"]["content"])


def locate_text_button(cfg, image, target, context, region="any"):
    h, w = image.shape[:2]
    result = ask_vision(cfg, image,
        f"Locate the exact labeled tappable UI target: {target}. "
        f"Expected screen context: {context}. "
        "If this is not the expected screen or target is missing, found=false. "
        "Return JSON with found boolean, confidence 0..1, "
        "and box [x1,y1,x2,y2] in full-image pixel coordinates.")
    confidence = result.get("confidence", 0)
    if result.get("found") is not True or isinstance(confidence, bool) or not isinstance(confidence, (int,float)) or confidence < .8 or confidence > 1:
        raise RuntimeError("Target not confidently detected")
    box = result.get("box")
    if not isinstance(box, list) or len(box) != 4 or any(isinstance(v,bool) or not isinstance(v,(int,float)) for v in box):
        raise ValueError("Invalid target bounding box")
    x1,y1,x2,y2 = box
    if not (0 <= x1 < x2 <= w and 0 <= y1 < y2 <= h):
        raise ValueError("Target box outside screenshot")
    x,y = round((x1+x2)/2),round((y1+y2)/2)
    if region == "bottom" and y < h*.7:
        raise RuntimeError("Target not in expected bottom UI region")
    return x,y


def check_rankings_screen(cfg, image):
    result = ask_vision(cfg, image,
        "Is this a Z-Route Alliance Competition rankings/leaderboard screen "
        "showing ranked players or alliances? Return JSON with "
        "rankings_screen boolean and confidence 0..1. Do not guess.")
    conf = result.get("confidence",0)
    return result.get("rankings_screen") is True and isinstance(conf,(int,float)) and not isinstance(conf,bool) and .8 <= conf <= 1
