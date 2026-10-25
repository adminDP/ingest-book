# Answering from this library

Start every answer by reading `INDEX.md`, then search before reading:
`grep -rni "<term>" books/*/chapters/ sites/*/pages/ wiki/` and open only the chapters that match.

## Sources, in order of authority

Edit this list (and `sources.json`) to match the library. Where two sources disagree, the higher one wins,
and the answer says that they disagree.

1. <primary book> — primary for <topic>. Check it first; answer from it whenever it speaks to the question.
2. <secondary book / primer> — for detail the primary does not cover.
3. <other books> — for their own frameworks (e.g. Beyond Budgeting for planning and budgeting).
4. Mirrored websites (`sites/`) — current practice and case studies; link the live URL.
5. `wiki/` — cross-source synthesis; follow its citations back to the chapters, never cite the wiki alone.
6. Conversation memory — continuity only, never a source of what a book claims.

## Rules

- Cite every claim from a source as `slug/chapters/file.md#pNN` (PDF page) and give the book title in prose.
- Figure descriptions (`> **[Figure ...]**`) count as the source's content; say "figure on p. NN".
- If the library is silent, say so, then answer from outside research or general knowledge, clearly marked
  as outside the library. Never present outside knowledge as a book's position.
- Quote sparingly and briefly; paraphrase by default.
