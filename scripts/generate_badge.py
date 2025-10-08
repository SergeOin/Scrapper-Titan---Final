#!/usr/bin/env python
"""Generate a simple coverage badge SVG from coverage.xml.

Fallbacks silently if coverage.xml missing or unparsable.
Writes coverage_badge.svg at repo root.
"""
from __future__ import annotations
import re
import pathlib
import sys

def parse_coverage(path: pathlib.Path) -> float | None:
    try:
        txt = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    m = re.search(r'line-rate="([0-9.]+)"', txt)
    if not m:
        return None
    try:
        return float(m.group(1)) * 100.0
    except Exception:
        return None


def color(pct: float) -> str:
    if pct >= 90: return "#2cbe4e"  # green
    if pct >= 80: return "#97CA00"
    if pct >= 70: return "#dfb317"
    if pct >= 60: return "#fe7d37"
    return "#e05d44"  # red


def main() -> int:
    cov = parse_coverage(pathlib.Path("coverage.xml"))
    if cov is None:
        print("coverage.xml missing or unparsable; skipping badge generation", file=sys.stderr)
        return 0
    pct_str = f"{cov:.1f}%"
    width_text = 50
    width_value = 54 if cov >= 100 else 46
    total_width = 98 if cov >= 100 else 90
    color_fill = color(cov)
    svg = f"""<svg xmlns='http://www.w3.org/2000/svg' width='{total_width}' height='20' role='img' aria-label='coverage: {pct_str}'>
  <linearGradient id='s' x2='0' y2='100%'>
    <stop offset='0' stop-color='#bbb' stop-opacity='.1'/>
    <stop offset='1' stop-opacity='.1'/>
  </linearGradient>
  <clipPath id='r'>
    <rect width='{total_width}' height='20' rx='3' fill='#fff'/>
  </clipPath>
  <g clip-path='url(#r)'>
    <rect width='{width_text}' height='20' fill='#555'/>
    <rect x='{width_text}' width='{width_value}' height='20' fill='{color_fill}'/>
    <rect width='{total_width}' height='20' fill='url(#s)'/>
  </g>
  <g fill='#fff' text-anchor='middle' font-family='Verdana,Geneva,DejaVu Sans,sans-serif' font-size='11'>
    <text x='{width_text/2:.1f}' y='15' fill='#010101' fill-opacity='.3'>coverage</text>
    <text x='{width_text/2:.1f}' y='14'>coverage</text>
    <text x='{width_text + width_value/2:.1f}' y='15' fill='#010101' fill-opacity='.3'>{pct_str}</text>
    <text x='{width_text + width_value/2:.1f}' y='14'>{pct_str}</text>
  </g>
</svg>"""
    pathlib.Path("coverage_badge.svg").write_text(svg, encoding="utf-8")
    print(f"Generated coverage_badge.svg ({pct_str})")
    return 0

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
