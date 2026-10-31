"""Opt-in pixel-change verification for desktop steps.

A screenshot is taken immediately before an action and compared against live
frames afterward. Use a tightly selected region to avoid unrelated desktop
animations being mistaken for success. A changed region means pixels changed,
not that a business operation semantically succeeded.
"""
from __future__ import annotations
from PIL import Image, ImageChops


def parse_region(text: str) -> dict | None:
    """Empty region samples the full virtual desktop; otherwise x,y,width,height."""
    if not str(text).strip():
        return None
    try:
        values = [int(part.strip()) for part in str(text).split(",")]
    except ValueError as exc:
        raise ValueError("Region must be x,y,width,height") from exc
    if len(values) != 4 or not all(-100000 <= coordinate <= 100000 for coordinate in values[:2]) \
       or not (1 <= values[2] <= 20000 and 1 <= values[3] <= 20000):
        raise ValueError("Region must be x,y,width,height with positive width and height")
    return dict(zip(("left", "top", "width", "height"), values))


def take_sample(region: str = "") -> Image.Image:
    import mss
    with mss.mss() as screen:
        rect = parse_region(region) or screen.monitors[0]
        shot = screen.grab(rect)
        return Image.frombytes("RGB", shot.size, shot.rgb)


def significant_change(before: Image.Image, after: Image.Image, delta: int = 25,
                       min_ratio: float = 0.0005) -> bool:
    if before.size != after.size:
        return True
    if before.size[0] < 1 or before.size[1] < 1:
        return False
    difference = ImageChops.difference(before.convert("RGB"), after.convert("RGB"))
    # Per-pixel change after a 25/255 channel threshold, with a minimum area
    # requirement so a blinking cursor alone is not sufficient for a large region.
    grayscale = difference.convert("L")
    changed = grayscale.point(lambda n: 255 if n > delta else 0)
    changed_pixels = changed.histogram()[255]
    return changed_pixels >= max(9, int(before.width * before.height * min_ratio))
