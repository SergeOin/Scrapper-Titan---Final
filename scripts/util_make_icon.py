from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


def make_ico(src: Path, dst: Path) -> None:
    img = Image.open(src).convert("RGBA")
    sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    img.save(dst, sizes=sizes)


def make_icns(src: Path, dst: Path) -> None:
    # Simple ICNS via pillow (creates 1024px variant if possible)
    img = Image.open(src).convert("RGBA")
    # Resize to a square canvas
    w, h = img.size
    m = max(w, h)
    canvas = Image.new("RGBA", (m, m), (0, 0, 0, 0))
    canvas.paste(img, ((m - w) // 2, (m - h) // 2))
    canvas.save(dst, format="ICNS")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("-i", "--input", required=True, help="Input PNG path")
    p.add_argument("-o", "--output", required=True, help="Output icon path (.ico or .icns)")
    args = p.parse_args()
    src = Path(args.input)
    dst = Path(args.output)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.suffix.lower() == ".ico":
        make_ico(src, dst)
    elif dst.suffix.lower() == ".icns":
        make_icns(src, dst)
    else:
        raise SystemExit("Unsupported output format; use .ico or .icns")


if __name__ == "__main__":
    main()
