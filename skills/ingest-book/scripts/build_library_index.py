#!/usr/bin/env python3
"""
build_library_index.py - (re)build LIBRARY/INDEX.md from every books/*/index.md and sites/*/index.md.

  python3 build_library_index.py LIBRARY_DIR

INDEX.md is the entry point an agent reads first: one row per source with authority rank, status,
size and a link to its own index. Authority ranks come from LIBRARY/sources.json if present:
  {"10x-org": {"rank": 1, "role": "primary for Org Topologies"}, ...}
"""
import json, re, sys
from pathlib import Path


def frontmatter(p):
    m = re.match(r"---\n(.*?)\n---", p.read_text(encoding="utf-8"), re.S)
    out = {}
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                v = v.split("  #")[0].strip()
                try:
                    out[k.strip()] = json.loads(v)
                except Exception:
                    out[k.strip()] = v
    return out


def main():
    lib = Path(sys.argv[1] if len(sys.argv) > 1 else "library")
    ranks = json.loads((lib / "sources.json").read_text()) if (lib / "sources.json").exists() else {}
    rows = []
    for idx in sorted(list(lib.glob("books/*/index.md")) + list(lib.glob("sites/*/index.md"))):
        fm = frontmatter(idx)
        slug = idx.parent.name
        todo = sum(len(re.findall(r"FIGURE-TODO", c.read_text(encoding="utf-8")))
                   for c in idx.parent.glob("chapters/*.md"))
        r = ranks.get(slug, {})
        rows.append((r.get("rank", 99), slug, fm, r.get("role", ""), todo, idx.relative_to(lib)))
    rows.sort(key=lambda x: (x[0], x[1]))
    lines = ["# Library index", "",
             "Read this first. Search with `grep -rn` over `books/*/chapters/` and `sites/*/pages/`; "
             "open a source's own `index.md` for its chapter map. Cite as `slug/chapters/file.md#pNN`.", "",
             "| Rank | Source | Author | Year | Words | Figures left | Status | Role |",
             "|---|---|---|---|---|---|---|---|"]
    for rank, slug, fm, role, todo, rel in rows:
        lines.append(f"| {rank if rank != 99 else '-'} | [{fm.get('title', slug)}]({rel}) | {fm.get('author', '')} | "
                     f"{fm.get('year') or ''} | {fm.get('words', '')} | {todo} | {fm.get('status', '')} | {role} |")
    lines += ["", "Sources not ranked in `sources.json` show '-'. Where ranked sources disagree, the lower rank wins.", ""]
    (lib / "INDEX.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"INDEX.md: {len(rows)} sources")


if __name__ == "__main__":
    main()
