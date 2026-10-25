# ingest-book

A Claude Code plugin that turns a PDF book, paper or website into a Markdown library Claude can `ls`, `grep`
and cite, instead of a PDF it can only skim.

For each book it produces:

- one Markdown file per chapter, split on the PDF outline or the printed table of contents
- a page anchor on every page (`chapters/10-org-topologies.md#p69`), with the printed page number alongside
- every figure extracted and described in text: diagram type, labels, arrows, and the point it makes
- footnotes as Markdown footnotes, running headers and page numbers removed, paragraphs re-joined across pages
- `index.md` with a summary, chapter table and key concepts linked to pages
- `qa-report.md` from a verification pass that compares rendered PDF pages with the Markdown

Scripts do the mechanical conversion; Claude only does what needs judgment (chapter map when there is no
outline, figure descriptions, summary, verification). Figure description can run on a cheaper model, and
verification is meant to run in a separate agent, so the converter doesn't grade its own work.

## Install

```bash
claude plugin marketplace add <github-user>/ingest-book
claude plugin install ingest-book@daniel-pokryvka
```

Python 3 with `pymupdf` and `pymupdf4llm<1` (the skill installs them; the 2.x wheel can install empty, hence the pin).

## Use

In a session: `/ingest-book:ingest-book path/to/book.pdf`, or just ask Claude to "ingest this book".

Optional library-level steps: rank the works your books cite most (`rank_references.py`), build concept pages
in the style of Karpathy's "LLM wiki" with citations back to chapters, and mirror websites such as less.works
to Markdown (`site_to_md.py`).

## Copyright

The plugin contains no book content. The libraries it produces do: keep them in a **private** repository and
don't publish personal copies of books or mirrored site content.

## Credits

Built from ideas by Alexey Krivitsky (Org Topologies): convert to Markdown, describe images as text, one file
per chapter with an index, cheap models for conversion with separate testing agents, and rank the books'
references to grow the library.
