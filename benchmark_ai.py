"""Read-only comparison of Ollama vision settings on saved screenshots."""
import argparse
import csv
import json
import time
from datetime import datetime
from pathlib import Path

import cv2
from scanner import ROOT, load_config, debug_ollama

VARIANTS = [
    ("baseline", "qwen3-vl:4b", 2048),
    ("optimized", "qwen3-vl:4b", 512),
    ("small", "qwen2.5vl:3b", 512),
]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--session", type=Path, help="Saved screenshot session folder; default latest")
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be positive")
    sessions = sorted((ROOT / "screenshots").glob("session_*"))
    folder = args.session or (sessions[-1] if sessions else None)
    if folder is None or not folder.is_dir():
        parser.error("No screenshot session found")
    images = sorted(folder.glob("capture_col_*_view_*.png"))[:args.limit]
    if not images:
        parser.error("No captures in selected session")
    cfg = load_config()
    cfg["_scan_session_folder"] = str(folder)
    output = folder / ("ai_benchmark_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".csv")
    fields = ["variant", "model", "num_predict", "image", "seconds", "valid", "players", "error"]
    results = []
    print(f"Benchmarking {len(images)} screenshots from {folder} (no map movement or CSV updates)")
    for label, model, tokens in VARIANTS:
        cfg["ollama"] = dict(cfg.get("ollama", {}), model=model, num_predict=tokens, keep_alive="30m")
        for index, path in enumerate(images, 1):
            start = time.perf_counter()
            valid, count, error = False, 0, ""
            try:
                image = cv2.imread(str(path))
                if image is None:
                    raise ValueError("Unreadable screenshot")
                players = debug_ollama(cfg, image=image)
                valid, count = True, len(players)
            except Exception as exc:
                error = str(exc)
            elapsed = round(time.perf_counter() - start, 2)
            results.append(dict(variant=label, model=model, num_predict=tokens,
                                image=path.name, seconds=elapsed, valid=valid,
                                players=count, error=error))
            print(f"{label} {index}/{len(images)}: {elapsed}s, valid={valid}, players={count}")
            with output.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(results)
    print("\nSummary (lower seconds per valid screenshot is better):")
    for label, _, _ in VARIANTS:
        rows = [r for r in results if r["variant"] == label]
        good = [r for r in rows if r["valid"]]
        total = sum(r["seconds"] for r in rows)
        print(f"{label}: {len(good)}/{len(rows)} valid, {total:.1f}s total, "
              f"{total/len(good):.1f}s per valid" if good else f"{label}: 0 valid")
    print(f"Saved benchmark results: {output}")
    print("Existing .players.json, .failed.json and player CSV files were not modified.")

if __name__ == "__main__":
    main()
