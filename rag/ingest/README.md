# Local portfolio ingestion

Run `make rag-models` once, then `make rag-ingest` after provisioning users with
`make mcp-bootstrap`. Model setup is explicit; no tool call downloads a model.

Sources: Markdown/frontmatter, text-based PDF, README, text, and local code files.
The existing persona CVs/case studies/reviews/proposals are used as-is. GitHub
integration and OCR are deferred. Files above 2 MB, unreadable PDFs, and escaping
symlinks are rejected. Missing metadata remains null/empty, not guessed.

WordPiece chunks contain 200 tokens with 40-token overlap. start/end are character
offsets in normalized document text (frontmatter removed, PDF text extracted),
not raw PDF byte positions. Each chunk retains source identity/hash, persona,
type, project, skills, date, industry, and outcome. Complete typed chunk metadata
and vectors live in the ignored per-user manifest; Chroma stores cosine vectors,
text, and primitive filtering metadata. BM25 uses the same manifest snapshot.

The explicit ingestion command locks publication per user, reuses unchanged
embeddings, embeds new/modified chunks, deletes obsolete vectors, and atomically
publishes the manifest. Queries refuse changed/deleted sources until re-ingestion.
Newly added files become searchable after explicit ingestion. Re-running ingestion
without source/model changes should report embedded=0.

A model digest or chunk/tokenizer change makes the old index incompatible.
Run model setup and re-ingestion after those changes; there is no lexical fallback.
Model artifacts/indexes are under data/processed/rag and must not be committed.
