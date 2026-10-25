---
name: ingest-book
description: Convert a book, paper or website into a greppable Markdown library (chapter files, page anchors, figures described as text, index, QA) for Claude to answer from. Use for "ingest this book", "LLMfy", "convert PDF to markdown for Claude", "build my library/LLM wiki".
---

# Ingest a book into the Markdown library

Turns a PDF (or a website) into a folder of Markdown files that an agent can `ls`, `grep` and cite,
with every figure described in words. Scripts do the mechanical conversion; the model only does the
parts that need judgment (chapter map when there is no outline, figure descriptions, summaries, QA).

## Why Markdown beats the PDF

- **Search**: `grep -rn "feature team" library/` works; it does not work on a PDF. Hard-wrapped lines are
  re-joined so phrases are found on one line.
- **Load only what is needed**: one file per chapter, so an answer reads 5k words, not 150k.
- **Citations that resolve**: every page has an anchor (`chapters/04-x.md#p57`), every chapter has
  frontmatter with book, author and page range.
- **Pictures survive**: diagrams become text descriptions; plain text extraction drops them silently.
- Note: claude.ai Project knowledge already text-extracts PDFs for retrieval. The library pays off most
  where Claude has a filesystem (Claude Code, a session with the repo attached), plus the figure text and
  chapter index help everywhere, including when the Markdown is uploaded to a Project instead of the PDF.

## Library layout

```
library/
  INDEX.md                 # entry point: every source, authority rank, status  (build_library_index.py)
  sources.json             # authority order, e.g. {"10x-org": {"rank": 1, "role": "primary for OT"}}
  CLAUDE.md                # answering rules (copy templates/CLAUDE.md and edit)
  references-ranked.md     # most-cited works across books   (rank_references.py)
  books/<slug>/
    index.md               # metadata, summary, chapter table, key concepts
    chapters/NN-title.md   # one file per chapter, <a id="pNN"> page anchors
    assets/pNNN-MM.png     # extracted figures
    references.md          # raw bibliography
    qa-report.md           # what to check
    figures/queue-*.jsonl  # figure-description work queue
  sites/<slug>/pages/*.md  # mirrored websites (site_to_md.py)
  wiki/<term>.md           # optional concept pages linking back to chapters
```

Slugs are short and stable (`less-1-scaling`, `10x-org`, `beyond-budgeting`). They are what citations use.

## Setup (once per environment)

```bash
pip install pymupdf "pymupdf4llm<1" markdownify beautifulsoup4 requests
python3 -c "import pymupdf4llm"   # if this fails, the 2.x wheel installed empty: keep the <1 pin
```
For scanned PDFs (QA report says SCANNED-NO-TEXT): `ocrmypdf in.pdf out.pdf` first, then ingest `out.pdf`.

## Workflow per book

Make a task list with these steps. Steps 2 and 3 are where quality is won; do not skip them.

### 1. Convert (script, no LLM)

```bash
python3 scripts/pdf_to_md.py BOOK.pdf --out library/books/<slug> \
  --title "..." --author "..." --year 2016 --render-diagrams
```
Read the JSON it prints. Check `split_method`:
- `pdf-outline` or `heading-hN` with a sensible chapter count: open `index.md`, sanity-check the table.
- `none ...`, or chapters that are clearly wrong (one giant file, dozens of tiny ones, running headers as
  titles): render the printed table of contents (`scripts/render_pages.py BOOK.pdf 2-6 --out tmp`), view it,
  write `chapters.json` as `[{"title": "...", "page": <printed page>}, ...]`, find the offset
  (PDF page index minus printed page number, e.g. PDF page 12 shows "Page 11" → offset 1) and rerun with
  `--chapters chapters.json --page-offset N`. Choose the level a reader would cite (chapters, or parts
  for short primers), not every subsection.

Page anchors use the **PDF page index**. The script strips running headers and page-number footers, records the printed number in each page comment (`<!-- page 67 (printed 57) -->`), writes `page_offset` to `index.md`, re-joins paragraphs split by a page break (inline `<a id>` anchor), converts footnotes to `[^n]`, and restores hyphens lost at line breaks from the book's own spelling. Cite printed pages to people, anchors to files.

### 2. Describe figures (cheap model, in parallel)

```bash
python3 scripts/figures.py queue library/books/<slug> --batch 15
```
This writes one queue line per *unique* image (repeated logos collapse into one) with the surrounding text.
Give each `queue-NN.jsonl` to a worker running a cheaper model (Haiku or Sonnet subagent if the user agreed
to subagents; otherwise do it yourself). Worker instructions:

> For each line: view `image`, read `context_before`/`context_after`, and append to `results-NN.jsonl`
> one line `{"hash": ..., "decorative": bool, "description": "..."}`.
> decorative = true for logos, author photos, icons, ornaments, QR codes, stock photos that carry no idea.
> Otherwise describe what a reader would need if they could not see it: the type (2x2 matrix, flow, table,
> timeline, causal-loop diagram), every label and axis verbatim, what connects to what and in which
> direction, numbers, and in one final sentence the point the figure makes in context. Transcribe tables
> as Markdown tables. Do not add knowledge that is not in the figure or its context.

Then apply each results file:
```bash
python3 scripts/figures.py apply library/books/<slug> results-NN.jsonl
```
It reports `remaining_todo`; repeat until 0. Pages flagged `VECTOR-DIAGRAM` were rendered as whole-page
images: describe only the diagram, not the body text that is already in the Markdown.

### 3. Verify (separate agent, fresh context)

The converter should not grade its own work. Have a different agent (or a fresh pass) do this:
1. Read `qa-report.md`. Render the suggested sample pages plus every flagged page with `render_pages.py`
   and compare each image against the Markdown for that page (`grep -n '<a id="pNN">'`).
2. Check: missing or duplicated paragraphs, reading order in multi-column pages, tables flattened into text,
   headings at the wrong level, running headers/footers mid-paragraph, broken hyphenation (`coordi-nation`),
   figure descriptions that contradict the image.
3. Answer 5 questions a practitioner would ask the book using only the Markdown, each with a
   `chapter#pNN` citation, then check each citation in the PDF render.
4. Write findings into `qa-report.md` under `## Verification` as a table (page, issue, severity, fixed?),
   fix what is fixable with Edit, and only then set `status: verified` in `index.md`.

### 4. Index

- Fill `SUMMARY-TODO` (5-8 sentences on the argument) and `CONCEPTS-TODO` (term → `chapters/file.md#pNN`,
  20-40 entries, the book's own vocabulary) in the book's `index.md`.
- Add the book to `sources.json` with a rank and a role, then `python3 scripts/build_library_index.py library`.

## Library-level steps (optional, after several books)

**References → reading list.** `python3 scripts/rank_references.py library --top 50` ranks works by how
many of your books cite them. The fingerprint is heuristic: clean up the top of the list, merge duplicates,
and propose an acquisition list. Acquire legally (open-access papers, publisher copies); never fetch
pirated copies.

**Wiki (Karpathy "LLM wiki" pattern).** For terms that recur across sources (feature team, Product Owner,
rolling forecast, archetype, Teal), write `wiki/<term>.md`: a short definition, then one section per source
stating what *that source* says with a `[[slug]]` link and `chapter#pNN` citation, then "Tensions" where
sources disagree. Every sentence is either attributed to a source or explicitly marked as synthesis. Use
`[[term]]` links between wiki pages so it opens as an Obsidian vault.

**Websites.** `python3 scripts/site_to_md.py https://less.works --out library/sites/less-works --include /less/`
mirrors pages from the sitemap (robots.txt respected, 1 s delay), with images as `[IMAGE: alt | url]`
placeholders. Needs network access to the site: run it in Claude Code on the user's machine, or after the
domain is allowed in this workspace. Re-run periodically; sites change, books do not.

## Publishing

- Store the library in a **private** GitHub repository. Personal copies of books (often watermarked with the
  owner's name) and mirrored site content are for personal use; never make the repo public.
- Commit per book (`ingest: 10x-org converted`, `... figures`, `... verified`) so regressions are diffable.
- Copy `templates/CLAUDE.md` to `library/CLAUDE.md` and edit the authority order. In a claude.ai Project,
  upload `INDEX.md`, the book `index.md` files and the chapter files instead of (or next to) the PDFs, and
  paste the answering rules into the Project instructions.

## Known limits

- Multi-column layouts and sidebars can interleave; that is what step 3 is for.
- De-hyphenation: common suffixes are joined (`manage-ment`) and hyphens are restored when the book spells the word with one elsewhere; a few compounds still come out glued (`commandand-control`).
- Re-running `pdf_to_md.py` rewrites `chapters/`: keep `figures/results-*.jsonl` outside the book folder and re-apply them, and redo hand edits. Finish script fixes before writing summaries or verification notes.
- `rank_references.py` and the heading heuristic are deliberately simple; they produce drafts for judgment.
- Text inside raster images (screenshots of slides) is only captured through the figure descriptions.
