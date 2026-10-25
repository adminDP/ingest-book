#!/usr/bin/env python3
"""render_pages.py PDF PAGES --out DIR  - render PDF pages (e.g. "1,12,40-42") to PNG for side-by-side QA."""
import argparse
from pathlib import Path
import pymupdf

ap = argparse.ArgumentParser(); ap.add_argument("pdf"); ap.add_argument("pages"); ap.add_argument("--out", required=True)
ap.add_argument("--dpi", type=int, default=110); a = ap.parse_args()
nums = []
for part in a.pages.split(","):
    lo, _, hi = part.partition("-"); nums += range(int(lo), int(hi or lo) + 1)
out = Path(a.out); out.mkdir(parents=True, exist_ok=True); doc = pymupdf.open(a.pdf)
for n in nums:
    if 1 <= n <= doc.page_count:
        doc[n - 1].get_pixmap(dpi=a.dpi).save(out / f"page-{n:03d}.png"); print(out / f"page-{n:03d}.png")
