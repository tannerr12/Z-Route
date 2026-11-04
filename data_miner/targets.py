"""Locate the VS event entry dynamically using the existing Ollama vision model."""
import base64
import json
import urllib.request

import cv2


def locate_vs_icon(cfg, image):
    height, width = image.shape[:2]
    ok, png = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError("Unable to encode screenshot")
    payload = {
        "model": cfg.get("ollama", {}).get("model", "qwen2.5vl:3b"),
        "stream": False,
        "format": "json",
        "options": {"temperature": 0},
        "messages": [{
            "role": "user",
            "content": (
                "Find the tappable VS event entry in this Z-Route city screenshot. "
                "There may be multiple VS logos: select the standalone event entry "
                "in the vertical right-side menu, not a top countdown badge. "
                "Return ONLY JSON: {\"found\": boolean, \"box\": [x1,y1,x2,y2] "
                "or null, \"confidence\": number}. Coordinates must be PIXELS "
                f"relative to the FULL image, width={width}, height={height}. "
                "If ambiguous or not visible, found=false. Do not guess."
            ),
            "images": [base64.b64encode(png.tobytes()).decode("ascii")]
        }]
    }
    request = urllib.request.Request(
        "http://127.0.0.1:11434/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=180) as response:
        result = json.load(response)
    if not result.get("done"):
        raise RuntimeError("Incomplete vision model response")
    answer = json.loads(result["message"]["content"])
    confidence = answer.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ValueError("Invalid detection confidence")
    if not 0 <= confidence <= 1:
        raise ValueError("Confidence out of range")
    if answer.get("found") is not True or confidence < 0.8:
        raise RuntimeError("VS icon not confidently located")
    box = answer.get("box")
    if not isinstance(box, list) or len(box) != 4 or any(
        isinstance(v, bool) or not isinstance(v, (int, float)) for v in box
    ):
        raise ValueError("Invalid VS bounding box")
    x1, y1, x2, y2 = box
    if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
        raise ValueError("VS bounding box outside screenshot")
    cx, cy = round((x1+x2)/2), round((y1+y2)/2)
    # Broad safety zone only: the icon location itself comes from vision.
    if not (cx >= width * 0.65 and height * 0.2 <= cy <= height * 0.85):
        raise RuntimeError("Detected VS target is outside right-side event menu")
    if x2-x1 > width * .25 or y2-y1 > height * .18:
        raise RuntimeError("VS bounding box unusually large")
    return cx, cy
