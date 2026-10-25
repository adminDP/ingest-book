#!/usr/bin/env python3
"""
figures.py - turn FIGURE-TODO markers into text descriptions, in batches.

  queue  BOOK_DIR [--batch 15]   -> BOOK_DIR/figures/queue-NN.jsonl (one line per UNIQUE image)
  apply  BOOK_DIR RESULTS.jsonl  -> replaces markers in chapters/*.md with the descriptions

Each queue line: {"hash", "ids", "image", "page", "size", "likely_decorative", "context_before", "context_after"}
Each results line (written by the describing agent): {"hash": "...", "decorative": false, "description": "..."}
  decorative=true removes the image link and the marker (logos, icons, author photos, page ornaments).

Identical images (same md5) are described once and applied everywhere they occur.
"""
import argparse, hashlib, json, re, sys
from pathlib import Path

MARK = re.compile(r"<!-- FIGURE-TODO (p\d{3}-[\w]+):[^>]*-->")
IMG = re.compile(r"!\[[^\]]*\]\(\.\./assets/(p\d{3}-[\w]+)\.png\)")


def strip(s):
    s = re.sub(r"\A---\n.*?\n---\n", "", s, flags=re.S)
    s = re.sub(r"^> Source:.*$", "", s, flags=re.M)
    s = MARK.sub("", IMG.sub("", s))
    s = re.sub(r"<!--.*?-->|<a id=[^>]+></a>", "", s)
    return re.sub(r"\s+", " ", s).strip()


def queue(book, batch):
    import pymupdf
    entries = {}
    for ch in sorted((book / "chapters").glob("*.md")):
        text = ch.read_text(encoding="utf-8")
        for m in MARK.finditer(text):
            fid = m.group(1)
            img = book / "assets" / f"{fid}.png"
            if not img.exists():
                continue
            h = hashlib.md5(img.read_bytes()).hexdigest()
            if h in entries:
                entries[h]["ids"].append(fid)
                continue
            px = pymupdf.Pixmap(str(img))
            entries[h] = {
                "hash": h, "ids": [fid], "image": str(img.resolve()), "page": int(fid[1:4]),
                "chapter": ch.name, "size": [px.width, px.height],
                "likely_decorative": max(px.width, px.height) < 150,
                "context_before": strip(text[max(0, m.start() - 1500):m.start()])[-500:],
                "context_after": strip(text[m.end():m.end() + 1200])[:300],
            }
    out = book / "figures"
    out.mkdir(exist_ok=True)
    items = list(entries.values())
    files = []
    for i in range(0, len(items), batch):
        f = out / f"queue-{i // batch:02d}.jsonl"
        f.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in items[i:i + batch]) + "\n",
                     encoding="utf-8")
        files.append(str(f))
    n_markers = sum(len(e["ids"]) for e in items)
    print(json.dumps({"unique_images": len(items), "markers": n_markers,
                      "likely_decorative": sum(e["likely_decorative"] for e in items),
                      "batches": files}, indent=2))


def apply(book, results_path):
    results = {}
    for line in Path(results_path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            results[r["hash"]] = r
    # map figure id -> hash via the queue files
    id2hash = {}
    for q in (book / "figures").glob("queue-*.jsonl"):
        for line in q.read_text(encoding="utf-8").splitlines():
            e = json.loads(line)
            for fid in e["ids"]:
                id2hash[fid] = e["hash"]
    done = removed = 0
    for ch in sorted((book / "chapters").glob("*.md")):
        text = ch.read_text(encoding="utf-8")

        def repl(m):
            nonlocal done, removed
            fid = m.group(1)
            r = results.get(id2hash.get(fid))
            if not r:
                return m.group(0)
            if r.get("decorative"):
                removed += 1
                return "<!-- FIGURE-DECORATIVE-REMOVED -->"
            done += 1
            desc = r["description"].strip().replace("\n", "\n> ")
            return f"> **[Figure {fid}, p. {int(fid[1:4])}]** {desc}"
        new = MARK.sub(repl, text)
        # drop image links whose marker was removed as decorative
        new = re.sub(r"!\[[^\]]*\]\(\.\./assets/[^)]+\)\s*\n\s*<!-- FIGURE-DECORATIVE-REMOVED -->\n?", "", new)
        new = new.replace("<!-- FIGURE-DECORATIVE-REMOVED -->", "")
        if new != text:
            ch.write_text(new, encoding="utf-8")
    left = sum(len(MARK.findall(c.read_text(encoding="utf-8"))) for c in (book / "chapters").glob("*.md"))
    print(json.dumps({"described": done, "decorative_removed": removed, "remaining_todo": left}))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("queue"); q.add_argument("book"); q.add_argument("--batch", type=int, default=15)
    a = sub.add_parser("apply"); a.add_argument("book"); a.add_argument("results")
    args = ap.parse_args()
    book = Path(args.book)
    if not (book / "chapters").is_dir():
        sys.exit(f"{book} has no chapters/ - run pdf_to_md.py first")
    queue(book, args.batch) if args.cmd == "queue" else apply(book, args.results)


if __name__ == "__main__":
    main()
