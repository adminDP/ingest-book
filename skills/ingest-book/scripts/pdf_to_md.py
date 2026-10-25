#!/usr/bin/env python3
"""
pdf_to_md.py - deterministic PDF -> Markdown ingestion for an LLM-readable library.

Does the mechanical part (no LLM needed):
  * converts every page to Markdown (headings, lists, tables) with page anchors
  * extracts figures to assets/ and leaves a FIGURE-TODO marker for each one
  * flags pages that are vector diagrams (no bitmap) or scanned (no text layer)
  * splits the book into one file per chapter (PDF outline first, heading heuristic second)
  * writes index.md (chapters, page ranges, word counts, figures) and qa-report.md
  * pulls the bibliography / references section into references.md

Usage:
  python3 pdf_to_md.py BOOK.pdf --out library/books/<slug> --title "..." --author "..." [--year 2016]
         [--split-level auto|1|2] [--min-image 0.05] [--render-diagrams]

Requires: pymupdf, pymupdf4llm (pin "pymupdf4llm<1" if the 2.x wheel installs empty).
"""
import argparse, collections, datetime, json, re, sys
from pathlib import Path

try:
    import pymupdf
    import pymupdf4llm
except ImportError:
    sys.exit("Missing deps: pip install pymupdf 'pymupdf4llm<1'")

REF_HEADINGS = re.compile(r"^(?:#+\s*)?\**\s*(?:\d+[.)]?\s*)?(references|bibliography|recommended readings?|works cited|notes|endnotes|sources)\b[^a-z]*$",
                          re.I)


def slugify(s, maxlen=50):
    s = re.sub(r"[^\w\s-]", "", s.lower()).strip()
    s = re.sub(r"[\s_-]+", "-", s)
    return s[:maxlen].strip("-") or "untitled"


def words(s):
    return len(re.findall(r"\w+", s))


BLOCK_START = re.compile(r"^\s*([-*+]\s|[>|#]|\d+[.)]\s|!\[|<!--|<a |```|\[\^\d)")


SUFFIX = re.compile(r"(ment|tion|sion|ing|ed|ity|ness|ance|ence|able|ible|al|ly|er|ers|ive|ize|ise|ship|ous|ful|ism|ist|ure|ate|ated|ology)s?\b")


LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")


def footnotes(md):
    """'[6]' markers + a line '6Alexey ...' on the same page -> Markdown footnotes '[^6]' / '[^6]: Alexey ...'."""
    marks = set(re.findall(r"\[(\d{1,3})\]", md))
    if not marks:
        return md

    def note(m):
        n = m.group(1)
        return f"[^{n}]: {m.group(2)}" if n in marks else m.group(0)
    md = re.sub(r"(?m)^\[(\d{1,3})(?=[A-Z\u201c\"])", r"\1[", md)   # "[10Nicolay ...](url)" -> "10[Nicolay ...](url)"
    md2 = re.sub(r"(?m)^(\d{1,3})(?=[A-Z\u201c\"_\[*])(.*)$", note, md)
    done = set(re.findall(r"(?m)^\[\^(\d{1,3})\]:", md2))
    return re.sub(r"\[(\d{1,3})\]", lambda m: f"[^{m.group(1)}]" if m.group(1) in done else m.group(0), md2)


def clean_md(md):
    """Strip invisible chars and re-join hard-wrapped prose so phrases are greppable on one line."""
    md = md.replace("\u200b", "").replace("\u00ad", "").replace("\ufeff", "").replace("\u00a0", " ")
    # word-by-word emphasis from some PDF producers: "_There_ _are_" -> "_There are_"
    md = re.sub(r"\*\*[ \t]+\*\*", " ", md)
    md = re.sub(r"(?<=\w)_[ \t]+_(?=\S)", " ", md)
    md = re.sub(r"(?<=[\w.,;:!?\u201d\u2019-])_[ \t]+_", " ", md)
    md = re.sub(r"(?m)^(#{1,6})[ \t]+\*\*(.+?)\*\*[ \t]*$", r"\1 \2", md)     # "# **Title**" -> "# Title"
    md = re.sub(r"\b([a-z]{2,})- ([a-z]{2,})\b", r"\1\2", md)             # "cus- tomers" -> "customers"
    out = []
    for block in re.split(r"\n\s*\n", md):
        lines = [l.rstrip() for l in block.splitlines() if l.strip()]
        if len(lines) > 1 and not any(BLOCK_START.match(l) for l in lines):
            joined = lines[0]
            for l in lines[1:]:
                if re.search(r"[a-z]-$", joined) and l[:1].islower():
                    nxt = l.lstrip()
                    # "manage-|ment" -> "management", but keep real compounds: "end-|to-end"
                    joined = joined[:-1] + nxt if SUFFIX.match(nxt) else joined + nxt
                else:
                    joined += " " + l.lstrip()
            out.append(joined)
        elif lines and LIST_ITEM.match(lines[0]):
            # list block: fold wrapped continuation lines into their item
            items = []
            for l in lines:
                if LIST_ITEM.match(l) or not items:
                    items.append(l)
                elif items[-1].endswith("-") and l.lstrip()[:1].islower():
                    items[-1] = items[-1] + l.lstrip()
                else:
                    items[-1] += " " + l.lstrip()
            out.append("\n".join(items))
        else:
            out.append("\n".join(lines))
    md = "\n\n".join(out)
    md = re.sub(r"-_ _(?=[a-z])", "", md)          # "_organi-_ _zational_" -> "_organizational_"
    # second pass: line re-joining can create new "_ _" and "x- y" seams
    md = re.sub(r"(?<=[\w.,;:!?\u201d\u2019-])_[ \t]+_", " ", md)
    return re.sub(r"\b([a-z]{2,})- ([a-z]{2,})\b", r"\1\2", md)


def convert_pages(pdf, out, min_image, render_diagrams):
    """Return list of dicts: {page, md, figures, flags}."""
    assets = out / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(pdf)
    chunks = pymupdf4llm.to_markdown(
        doc, page_chunks=True, write_images=True, image_path=str(assets),
        image_format="png", image_size_limit=min_image, dpi=150, show_progress=False)
    pages = []
    for i, ch in enumerate(chunks):
        pno = i + 1
        page = doc[i]
        md = footnotes(clean_md(ch["text"]))
        flags = []
        raw_text = page.get_text().strip()
        if len(raw_text) < 30 and page.get_images():
            flags.append("SCANNED-NO-TEXT")  # needs OCR or vision transcription
        figures = []

        # Re-point image links to relative paths and add a description TODO under each.
        def repl(m):
            src = Path(m.group(2)).name
            fig_id = f"p{pno:03d}-{len(figures) + 1:02d}"
            new_name = f"{fig_id}.png"
            p_old = assets / src
            if p_old.exists():
                p_old.rename(assets / new_name)
            figures.append(fig_id)
            return (f"![Figure {fig_id}](../assets/{new_name})\n\n"
                    f"<!-- FIGURE-TODO {fig_id}: describe this figure in text (what it shows, labels, "
                    f"arrows/relationships, the point it makes) -->")
        md = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", repl, md)

        # Vector-drawn diagrams have no bitmap; render the page so the describer can see it.
        n_draw = len(page.get_drawings())
        if n_draw > 40 and not figures:
            flags.append(f"VECTOR-DIAGRAM({n_draw} paths)")
            if render_diagrams:
                fig_id = f"p{pno:03d}-page"
                page.get_pixmap(dpi=110).save(assets / f"{fig_id}.png")
                figures.append(fig_id)
                md += (f"\n\n![Page render {fig_id}](../assets/{fig_id}.png)\n\n"
                       f"<!-- FIGURE-TODO {fig_id}: this page contains a vector diagram; describe it -->")
        pages.append({"page": pno, "md": md.strip(), "figures": figures, "flags": flags,
                      "pdf_chars": len(raw_text)})
    toc = doc.get_toc()
    meta = doc.metadata
    doc.close()
    return pages, toc, meta


TERMINAL = re.compile(r"[.!?:;\u201d\u2019\"')\]>*_]\s*$")


TOKEN = re.compile(r"(?<![/\w-])[A-Za-z][A-Za-z-]{3,}[A-Za-z](?![\w/-])")


def fix_hyphen_vocab(pages):
    """Restore hyphens lost at line breaks using the book's own vocabulary:
    "Multilearning" -> "Multi-learning" when "multi-learning" is the dominant spelling in this book."""
    counts = collections.Counter(t.lower() for p in pages for t in TOKEN.findall(p["md"]))
    canon = {}
    for t, n in counts.items():
        if "-" in t:
            k = t.replace("-", "")
            if n > counts.get(canon.get(k, ""), 0):
                canon[k] = t
    fixed = 0

    def repl(m):
        nonlocal fixed
        t = m.group(0); low = t.lower(); c = canon.get(low.replace("-", ""))
        if c and c != low and counts[c] >= 2 and counts[c] >= 2 * counts[low]:
            fixed += 1
            return c[0].upper() + c[1:] if t[0].isupper() else c
        return t
    for p in pages:
        p["md"] = TOKEN.sub(repl, p["md"])
    return fixed


def strip_running(pages, titles=()):
    """Remove running headers ("Chapter 3: Title 57") and page-number footers; record printed page numbers.
    Then join paragraphs that continue across a page break, with an inline anchor for the new page."""
    def first_last(md):
        ls = [l for l in md.splitlines() if l.strip()]
        return (ls[0].strip() if ls else ""), (ls[-1].strip() if ls else "")
    head_pat = re.compile(r"^(?:\*\*)?(.{3,140}?)(?:\*\*)?\s+(\d{1,4})$")
    counts = collections.Counter()
    for p in pages:
        f, _ = first_last(p["md"])
        m = head_pat.match(f)
        if m:
            counts[norm(m.group(1))] += 1
    removed = 0
    for p in pages:
        lines = p["md"].splitlines()
        idx = [i for i, l in enumerate(lines) if l.strip()]
        if not idx:
            continue
        printed = None
        f = lines[idx[0]].strip()
        m = head_pat.match(f)
        if m and (counts[norm(m.group(1))] >= 3 or norm(m.group(1)) in titles):
            printed = int(m.group(2)); lines[idx[0]] = ""; removed += 1
        elif re.fullmatch(r"\d{1,4}", f) and len(idx) > 1:
            printed = int(f); lines[idx[0]] = ""; removed += 1
        last = lines[idx[-1]].strip()
        if re.fullmatch(r"(?:\*\*)?\d{1,4}(?:\*\*)?", last) and len(idx) > 1:
            printed = printed or int(last.strip("*")); lines[idx[-1]] = ""; removed += 1
        p["printed"] = printed
        p["md"] = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    joined = 0
    for a, b in zip(pages, pages[1:]):
        ab, bb = a["md"].split("\n\n"), b["md"].split("\n\n")
        if not ab or not bb or not ab[-1] or not bb[0]:
            continue
        tail, head = ab[-1], bb[0]
        if (not BLOCK_START.match(tail) and not BLOCK_START.match(head) and not TERMINAL.search(tail)
                and head[:1].islower()):
            ab[-1] = f'{tail} <a id="p{b["page"]}"></a>{head}'
            a["md"], b["md"] = "\n\n".join(ab), "\n\n".join(bb[1:])
            b["inline_anchor"] = True
            joined += 1
    return removed, joined


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def find_boundaries(pages, toc, args):
    """Return (list of (page, title), method). Priority: --chapters file > PDF outline > Markdown headings."""
    if args.chapters:
        spec = json.loads(Path(args.chapters).read_text(encoding="utf-8"))
        b = [(int(c["page"]) + args.page_offset, c["title"]) for c in spec]
        return dedupe(b, keep_same_page=True), "chapters-file"
    if toc:
        top = min(t[0] for t in toc)
        b = [(t[2], t[1].strip()) for t in toc if t[0] == top and t[2] > 0]
        if len(b) >= 3:
            return dedupe(b, keep_same_page=True), "pdf-outline"
    # Heading heuristic: pick the shallowest heading level that yields a sane number of sections.
    by_level = collections.defaultdict(list)
    for p in pages:
        for line in p["md"].splitlines():
            m = re.match(r"^(#{1,6})\s+(.+)$", line.strip())
            if m:
                title = re.sub(r"[*_`]", "", m.group(2)).strip()
                if 2 < len(title) < 120:
                    by_level[len(m.group(1))].append((p["page"], title))
    levels = range(1, 7) if args.split_level == "auto" else [int(args.split_level)]
    for lo, hi in ((5, 60), (3, 80)):  # prefer a level that gives a useful number of sections
        for lvl in levels:
            b = dedupe(by_level.get(lvl, []), keep_same_page=True)
            if lo <= len(b) <= hi:
                return b, f"heading-h{lvl}"
    return [(1, "Full text")], "none - read the printed TOC and rerun with --chapters"


def dedupe(b, keep_same_page=False):
    out, seen = [], set()
    for page, title in sorted(b, key=lambda x: x[0]):
        key = (page, norm(title)) if keep_same_page else page
        if key in seen:
            continue
        seen.add(key)
        out.append((page, title))
    if out and out[0][0] != 1:
        out.insert(0, (1, "Front matter"))
    return out


def cut_stream(pages, bounds):
    """Split the page stream into chapters, cutting at the title line when it can be found on the page."""
    stream = []  # (page, line)
    for p in pages:
        pr = f" (printed {p['printed']})" if p.get("printed") else ""
        stream.append((p["page"], f"<!-- page {p['page']}{pr} -->"))
        if not p.get("inline_anchor"):
            stream.append((p["page"], f'<a id="p{p["page"]}"></a>'))
        stream.append((p["page"], ""))
        stream.extend((p["page"], l) for l in p["md"].splitlines())
        stream.append((p["page"], ""))
    cuts = []
    for page, title in bounds:
        nt = norm(title)[:30]
        idx = next((i for i, (pg, l) in enumerate(stream)
                    if pg == page and nt and norm(l).startswith(nt) and (not cuts or i > cuts[-1])), None)
        if idx is None:
            idx = next(i for i, (pg, _) in enumerate(stream) if pg >= page)
        if cuts and idx <= cuts[-1]:
            continue
        cuts.append(idx)
        # keep the page anchor with a mid-page cut: re-emit it at the start of the chapter
    result = []
    for k, start in enumerate(cuts):
        stop = cuts[k + 1] if k + 1 < len(cuts) else len(stream)
        seg = stream[start:stop]
        first_page = seg[0][0]
        lines = [l for _, l in seg]
        if not lines[0].startswith("<!-- page") and not lines[0].startswith("<a id="):
            lines = [f"<!-- page {first_page} (continued) -->", f'<a id="p{first_page}"></a>', ""] + lines
        result.append((first_page, seg[-1][0], "\n".join(lines).strip()))
    return result, len(cuts)


def write_outputs(pages, toc, meta, args, out):
    chapters_dir = out / "chapters"
    chapters_dir.mkdir(parents=True, exist_ok=True)
    bounds, method = find_boundaries(pages, toc, args)
    by_no = {p["page"]: p for p in pages}
    last = pages[-1]["page"]
    segs, _ = cut_stream(pages, bounds)
    titles = [t for _, t in bounds]
    chapters, refs_text = [], []
    for idx, (start, end, text) in enumerate(segs):
        title = titles[idx] if idx < len(titles) else f"Section {idx}"
        fname = f"{idx:02d}-{slugify(title)}.md"
        for line in text.splitlines():
            if REF_HEADINGS.match(line):
                refs_text.append((start, title, text[text.index(line):]))
                break
        fm = {
            "book": args.title, "author": args.author, "year": args.year,
            "chapter": idx, "title": title, "pages": f"{start}-{end}",
            "source_pdf": Path(args.pdf).name,
        }
        header = "---\n" + "\n".join(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in fm.items()) + "\n---\n\n"
        cite = f"> Source: {args.author}, *{args.title}*, pp. {start}-{end}. Cite as `{out.name}/chapters/{fname}#p<page>`.\n\n"
        (chapters_dir / fname).write_text(header + cite + text + "\n", encoding="utf-8")
        figs = re.findall(r"FIGURE-TODO (p\d{3}-\w+)", text)
        chapters.append({"file": fname, "title": title, "start": start, "end": end,
                         "words": words(text), "figures": figs})

    # references.md - from a references-like heading to the end of that chapter
    ref_out = [f"## From '{t}' (starting p. {p})\n\n{body}" for p, t, body in refs_text]
    if ref_out:
        (out / "references.md").write_text(
            f"# References - {args.title}\n\nRaw extraction; normalize with rank_references.py.\n\n"
            + "\n\n".join(ref_out) + "\n", encoding="utf-8")

    # index.md
    total_words = sum(c["words"] for c in chapters)
    n_figs = sum(len(c["figures"]) for c in chapters)
    lines = [
        "---", f"title: {json.dumps(args.title, ensure_ascii=False)}",
        f"author: {json.dumps(args.author, ensure_ascii=False)}", f"year: {json.dumps(args.year)}",
        f"source_pdf: {json.dumps(Path(args.pdf).name, ensure_ascii=False)}",
        f"pages: {last}", f"words: {total_words}", f"figures: {n_figs}",
        f"split_method: {json.dumps(method)}",
        f"page_offset: {json.dumps(getattr(args, 'detected_offset', None))}   # PDF page - printed page",
        f"ingested: {datetime.date.today().isoformat()}",
        "status: converted   # -> figures-described -> verified", "---", "",
        f"# {args.title}", "", f"{args.author}{', ' + str(args.year) if args.year else ''}. "
        f"{last} pages, ~{total_words:,} words, {n_figs} figures.", "",
        "## Summary", "", "<!-- SUMMARY-TODO: 5-8 sentences on the book's argument and key concepts -->", "",
        "## Chapters", "", "| # | Chapter | Pages | Words | Figures |", "|---|---|---|---|---|",
    ]
    for i, c in enumerate(chapters):
        lines.append(f"| {i} | [{c['title']}](chapters/{c['file']}) | {c['start']}-{c['end']} | "
                     f"{c['words']:,} | {len(c['figures'])} |")
    lines += ["", "## Key concepts", "", "<!-- CONCEPTS-TODO: term -> chapter file#pNN, one per line -->", ""]
    (out / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # qa-report.md
    rs = getattr(args, "running_stats", (0, 0))
    qa = [f"# QA report - {args.title}", "", f"Split method: **{method}** ({len(chapters)} files).",
          f"Running headers/footers removed: {rs[0]}; paragraphs re-joined across page breaks: {rs[1]}; "
          f"page offset (PDF - printed): {getattr(args, 'detected_offset', None)}; "
          f"hyphens restored from book vocabulary: {getattr(args, 'hyphen_fixes', 0)}.", ""]
    flagged = [p for p in pages if p["flags"]]
    empty = [p["page"] for p in pages if len(p["md"]) < 20]
    low_yield = [p["page"] for p in pages if p["pdf_chars"] > 400 and len(p["md"]) < 0.5 * p["pdf_chars"]]
    garbled = [p["page"] for p in pages if p["md"] and
               sum(ch in "�" or (0xE000 <= ord(ch) <= 0xF8FF) for ch in p["md"]) > 5]
    qa += [f"- Figures awaiting description: **{n_figs}** (grep `FIGURE-TODO`)",
           f"- Pages flagged (scanned / vector diagram): {len(flagged)}",
           f"- Near-empty pages: {empty[:40]}{' ...' if len(empty) > 40 else ''}",
           f"- Low text yield vs PDF layer (<50%): {low_yield[:40]}",
           f"- Garbled glyphs (private-use / replacement chars): {garbled[:40]}", ""]
    if flagged:
        qa += ["## Flagged pages", ""] + [f"- p{p['page']}: {', '.join(p['flags'])}" for p in flagged] + [""]
    qa += ["## Suggested verification sample", "",
           "Pages for a verifier agent to compare PDF render vs Markdown: "
           + str(sorted(set([pages[0]["page"], last] + low_yield[:3] + garbled[:3]
                            + [c["start"] for c in chapters[1:4]])))]
    (out / "qa-report.md").write_text("\n".join(qa) + "\n", encoding="utf-8")
    return chapters, method, n_figs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf")
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--author", default="Unknown")
    ap.add_argument("--year", type=int)
    ap.add_argument("--chapters", help="JSON list of {title, page} read from the printed TOC; overrides auto-split")
    ap.add_argument("--page-offset", type=int, default=0,
                    help="PDF page index minus printed page number (add to --chapters pages)")
    ap.add_argument("--split-level", default="auto", choices=["auto", "1", "2", "3", "4", "5", "6"])
    ap.add_argument("--min-image", type=float, default=0.05,
                    help="skip images smaller than this fraction of the page (logos, icons)")
    ap.add_argument("--render-diagrams", action="store_true",
                    help="render pages with vector diagrams to PNG so they can be described")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    pages, toc, meta = convert_pages(args.pdf, out, args.min_image, args.render_diagrams)
    removed, joined = strip_running(pages, {norm(t[1]) for t in toc})
    args.hyphen_fixes = fix_hyphen_vocab(pages)
    offs = collections.Counter(p["page"] - p["printed"] for p in pages if p.get("printed"))
    args.detected_offset = offs.most_common(1)[0][0] if offs else None
    args.running_stats = (removed, joined)
    chapters, method, n_figs = write_outputs(pages, toc, meta, args, out)
    print(json.dumps({"out": str(out), "pages": len(pages), "chapters": len(chapters),
                      "split_method": method, "figures_todo": n_figs}, indent=2))


if __name__ == "__main__":
    main()
