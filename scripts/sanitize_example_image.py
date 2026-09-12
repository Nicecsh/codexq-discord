#!/usr/bin/env python3
"""Create a privacy-safe /codexq screenshot for project documentation."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

# Coordinates were calibrated against the source screenshot's 1260×1112 pixels.
# The output retains the bot response but excludes the top user-message section.
CROP = (0, 380, 1260, 1112)
# In cropped-image coordinates: reply avatar and @username, excluding the bot label.
IDENTITY_RECT = (190, 0, 480, 88)


def sanitize(source: Path, destination: Path) -> None:
    image = Image.open(source).convert("RGB")
    if image.size != (1260, 1112):
        raise ValueError(f"Unexpected source dimensions: {image.size}")

    cropped = image.crop(CROP)
    overlay = Image.new("RGBA", cropped.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    # An opaque UI-colored panel removes identity pixels; a blurred edge prevents
    # the result from looking like a raw black-box redaction.
    draw.rounded_rectangle(IDENTITY_RECT, radius=18, fill=(245, 240, 229, 255))
    overlay = overlay.filter(ImageFilter.GaussianBlur(radius=5))
    cropped = Image.alpha_composite(cropped.convert("RGBA"), overlay).convert("RGB")

    destination.parent.mkdir(parents=True, exist_ok=True)
    cropped.save(destination, quality=92, optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Sanitize a /codexq documentation screenshot")
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    sanitize(args.source, args.destination)


if __name__ == "__main__":
    main()
