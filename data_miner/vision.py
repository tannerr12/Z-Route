"""Classify Data Miner startup screens using the existing local Ollama vision service."""
import base64
import json
import urllib.request

import cv2


def classify_screen(cfg, image):
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError("Could not encode screenshot")
    request = {
        "model": cfg.get("ollama", {}).get("model", "qwen2.5vl:3b"),
        "stream": False,
        "format": "json",
        "messages": [{
            "role": "user",
            "content": (
                "Classify this Z-Route screenshot. Return only a JSON object "
                "with screen one of login_warning, promotion, city, other, unknown; "
                "and confidence between 0 and 1. login_warning means the "
                "account is logged in on another device and has a Confirm button. "
                "promotion means a fullscreen sales offer with a gold X in the "
                "upper-right. city means the home city view with resource bar, "
                "buildings and a VS event icon on the right. other means "
                "a different in-game screen. "
                "Do not invent screen types or coordinates."
            ),
            "images": [base64.b64encode(encoded.tobytes()).decode("ascii")]
        }],
        "options": {"temperature": 0}
    }
    req = urllib.request.Request(
        "http://127.0.0.1:11434/api/chat",
        data=json.dumps(request).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as response:
        result = json.load(response)
    if not result.get("done"):
        raise RuntimeError("Incomplete Ollama response")
    payload = json.loads(result["message"]["content"])
    screen = payload.get("screen")
    confidence = payload.get("confidence")
    if screen not in {"login_warning", "promotion", "city", "other", "unknown"}:
        raise ValueError("Unrecognized screen classification")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise ValueError("Invalid confidence")
    return screen, confidence
