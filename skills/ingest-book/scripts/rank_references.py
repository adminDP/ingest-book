#!/usr/bin/env python3
"""
rank_references.py - rank works cited across all ingested books (build-your-library step).

  python3 rank_references.py LIBRARY_DIR [--top 50]

Reads LIBRARY_DIR/books/*/references.md, splits them into entries, fingerprints each entry by
(first author surname, year) or, failing that, by its first quoted/italic title, and counts how many
DIFFERENT books cite it. Writes LIBRARY_DIR/references-ranked.md and references-ranked.json.

Heuristic by design: it gives Claude a ranked shortlist to clean up and decide what to acquire,
not a bibliographic database. Entries in the output keep one raw example citation per book.
"""
import argparse, collections, json, re
from pathlib import Path

YEAR = re.compile(r"\b(19[5-9]\d|20[0-4]\d)[a-z]?\b")
TITLE = re.compile(r"[_*]{1,2}([^_*]{6,120})[_*]{1,2}|[“\"]([^”\"]{6,120})[”\"]")
STOP = {"the", "a", "an", "and", "of", "in", "on", "for", "see", "also", "et", "al", "ed", "eds", "by", "at"}


def entries(md):
    md = re.sub(r"<!--.*?-->|<a id=[^>]+></a>", "", md, flags=re.S)
    md = re.sub(r"^#+.*$|^\*\*\d+\*\*$", "", md, flags=re.M)
    parts = re.split(r"\n\s*\n|\n\s*(?:[-•?·]|\d+\.)\s+", md)
    for p in parts:
        p = re.sub(r"\s+", " ", p).strip(" -•?·")
        if 25 <= len(p) <= 600:
            yield p


def fingerprint(e):
    title = None
    m = TITLE.search(e)
    if m:
        title = (m.group(1) or m.group(2)).strip().rstrip(".,")
    y = YEAR.search(e)
    words = [w for w in re.findall(r"[A-Z][a-zA-Z'\-]+", e[:80]) if w.lower() not in STOP]
    if y and words:
        return f"{words[0].lower()}-{y.group(1)}", title
    if title:
        return "t:" + re.sub(r"[^a-z0-9]+", "-", title.lower())[:60], title
    return None, None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("library")
    ap.add_argument("--top", type=int, default=50)
    a = ap.parse_args()
    lib = Path(a.library)
    hits = collections.defaultdict(lambda: {"books": {}, "titles": collections.Counter()})
    for ref in sorted(lib.glob("books/*/references.md")):
        book = ref.parent.name
        for e in entries(ref.read_text(encoding="utf-8")):
            key, title = fingerprint(e)
            if not key:
                continue
            h = hits[key]
            h["books"].setdefault(book, e)
            if title:
                h["titles"][title] += 1
    ranked = sorted(hits.items(), key=lambda kv: (-len(kv[1]["books"]), kv[0]))
    rows = []
    for key, h in ranked[:a.top]:
        rows.append({"key": key, "cited_by": len(h["books"]), "books": sorted(h["books"]),
                     "title_guess": h["titles"].most_common(1)[0][0] if h["titles"] else None,
                     "example": next(iter(h["books"].values()))})
    (lib / "references-ranked.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    md = ["# Most-cited works across the library", "",
          f"Heuristic ranking over {len(list(lib.glob('books/*/references.md')))} books. "
          "Verify each before acquiring; merge duplicates the fingerprint missed.", "",
          "| # | Cited by | Work (best guess) | Books | Example citation |", "|---|---|---|---|---|"]
    for i, r in enumerate(rows, 1):
        ex = r["example"].replace("|", "/")[:160]
        md.append(f"| {i} | {r['cited_by']} | {r['title_guess'] or r['key']} | {', '.join(r['books'])} | {ex} |")
    (lib / "references-ranked.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps({"unique_works": len(hits), "written": str(lib / "references-ranked.md"),
                      "top5": [(r["title_guess"] or r["key"], r["cited_by"]) for r in rows[:5]]},
                     indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
