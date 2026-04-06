#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import tempfile
import time
from pathlib import Path

from PIL import Image

SCREENSHOT_HELPER = Path("/Users/jeff/.codex/skills/screenshot/scripts/take_screenshot.py")


def run_osascript(script: str) -> str:
    return subprocess.check_output(["osascript", "-e", script], text=True).strip()


def get_front_chrome_window() -> tuple[int, str]:
    script = """
    tell application "Google Chrome"
      set frontWindow to front window
      return (id of frontWindow as string) & "||" & (title of active tab of frontWindow as string)
    end tell
    """
    out = run_osascript(script)
    window_id_text, title = out.split("||", 1)
    return int(window_id_text), title


def get_front_tab_url() -> str:
    return run_osascript('tell application "Google Chrome" to get URL of active tab of front window')


def get_front_system_chrome_window() -> tuple[int, str]:
    output = subprocess.check_output(
        ["python3", str(SCREENSHOT_HELPER), "--list-windows", "--app", "Google Chrome"],
        text=True,
    )
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("Could not find any Google Chrome windows")
    first = lines[0]
    parts = first.split("\t")
    if len(parts) < 3:
        raise RuntimeError(f"Unexpected window listing format: {first}")
    return int(parts[0]), parts[2]


def activate_chrome() -> None:
    run_osascript('tell application "Google Chrome" to activate')


def go_to_page(page_num: int) -> None:
    current_url = get_front_tab_url()
    base_url = current_url.split("#p=", 1)[0]
    target_url = f"{base_url}#p={page_num}"
    script = """
    tell application "Google Chrome"
      set URL of active tab of front window to "%s"
    end tell
    """ % target_url.replace('"', '\\"')
    run_osascript(script)


def capture_window(system_window_id: int, out_path: Path) -> None:
    temp_path = subprocess.check_output(
        ["python3", str(SCREENSHOT_HELPER), "--window-id", str(system_window_id), "--mode", "temp"],
        text=True,
    ).strip()
    Path(temp_path).replace(out_path)


def crop_page_from_window(window_png: Path, out_path: Path) -> tuple[int, int, int, int]:
    image = Image.open(window_png).convert("RGBA")
    width, height = image.size
    # Ignore the browser chrome and translation popup near the very top.
    search_left = int(width * 0.08)
    search_right = int(width * 0.88)
    search_top = int(height * 0.17)
    search_bottom = int(height * 0.90)
    background = (60, 60, 60)
    tolerance = 18

    min_x, min_y = search_right, search_bottom
    max_x, max_y = search_left, search_top
    found = False

    pixels = image.load()
    for y in range(search_top, search_bottom):
        for x in range(search_left, search_right):
            r, g, b, a = pixels[x, y]
            if a < 200:
                continue
            if abs(r - background[0]) <= tolerance and abs(g - background[1]) <= tolerance and abs(b - background[2]) <= tolerance:
                continue
            found = True
            if x < min_x:
                min_x = x
            if y < min_y:
                min_y = y
            if x > max_x:
                max_x = x
            if y > max_y:
                max_y = y

    if not found:
        raise RuntimeError(f"Could not detect page content area in {window_png}")

    pad_x = 12
    pad_y = 12
    crop_box = (
        max(0, min_x - pad_x),
        max(0, min_y - pad_y),
        min(width, max_x + pad_x),
        min(height, max_y + pad_y),
    )
    cropped = image.crop(crop_box)
    cropped.save(out_path)
    return crop_box


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture FlipHTML5 book pages from the front Chrome window")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--pages", type=int, default=3)
    parser.add_argument("--start-page", type=int, default=1)
    parser.add_argument("--delay", type=float, default=1.2, help="Seconds to wait after each page turn")
    args = parser.parse_args()

    output_dir = Path(args.output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    activate_chrome()
    chrome_window_id, chrome_title = get_front_chrome_window()
    system_window_id, system_title = get_front_system_chrome_window()
    print(
        f"chrome_window_id={chrome_window_id} system_window_id={system_window_id} chrome_title={chrome_title} system_title={system_title}",
        flush=True,
    )

    with tempfile.TemporaryDirectory(prefix="fliphtml_capture_") as tmp_dir:
        tmp_dir_path = Path(tmp_dir)
        for page_num in range(args.start_page, args.start_page + args.pages):
            raw_path = tmp_dir_path / f"raw_{page_num:03d}.png"
            out_path = output_dir / f"page_{page_num:03d}.png"
            go_to_page(page_num)
            time.sleep(args.delay)
            capture_window(system_window_id, raw_path)
            crop_box = crop_page_from_window(raw_path, out_path)
            print(f"saved {out_path} crop={crop_box}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
