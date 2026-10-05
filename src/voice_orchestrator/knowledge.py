"""Knowledge base core (blocco 5): how a document becomes chunks, and how a
query finds them. One implementation shared by the `knowledge_lookup` tool
(what an agent actually gets mid-call) and the agent builder's preview (what
the editor sees when testing a question) — so the preview can't drift from
the real retrieval.

Documents are plain files in `config.KNOWLEDGE_DIR` (markdown or text),
referenced by file name from an agent's `knowledge:` list. The files are the
source of truth for content, read the same way by the CLI, the voice worker
and the web API: unlike the agent family (D4), there's no second copy to
keep in step. The web API only adds metadata about where a document came
from (`webapi/models.py`'s `KnowledgeDocRow`).

Retrieval stays BM25 only (see tools/knowledge_tool.py's docstring for why):
lexical, so a query has to share words with a chunk to find it — an Italian
question against an English document finds little. The preview shows the
scores precisely so that's visible instead of surprising.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import bm25s

from . import config

# A chunk longer than this is split further on paragraph boundaries. The
# bundled demo files have short `##` sections and are unaffected; this is
# for pasted text or a scraped page with few or no headers, which would
# otherwise become one giant chunk that matches everything a little.
MAX_CHUNK_CHARS = 1200

ALLOWED_SUFFIXES = (".md", ".txt")


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zàèéìòù0-9]+", text.lower())


def _is_heading_only(section: str) -> bool:
    return all(line.lstrip().startswith("#") for line in section.splitlines() if line.strip())


def _split_long(section: str) -> list[str]:
    if len(section) <= MAX_CHUNK_CHARS:
        return [section]
    lines = section.splitlines()
    # Keep the section's heading on every piece, so a piece still says what
    # it's about (and BM25 still sees the heading's words).
    heading = lines[0] if lines and lines[0].lstrip().startswith("#") else ""
    body = "\n".join(lines[1:] if heading else lines)
    pieces: list[str] = []
    current = ""
    for para in (p.strip() for p in re.split(r"\n\s*\n", body)):
        if not para:
            continue
        # A single paragraph over the limit is cut on sentence ends.
        parts = [para] if len(para) <= MAX_CHUNK_CHARS else re.split(r"(?<=[.!?])\s+", para)
        for part in parts:
            if current and len(current) + len(part) + 2 > MAX_CHUNK_CHARS:
                pieces.append(current)
                current = ""
            current = f"{current}\n\n{part}" if current else part
    if current:
        pieces.append(current)
    return [f"{heading}\n{p}" if heading else p for p in pieces]


def chunk_text(text: str) -> list[str]:
    """Split on `##` (and deeper) section headers first — don't cut a
    section in half — then split any section still over MAX_CHUNK_CHARS on
    paragraphs. A section with nothing but headings (a document title before
    the first `##`) isn't a chunk of its own: it has nothing to ground on."""
    sections = re.split(r"\n(?=#{2,6}\s)", text.replace("\r\n", "\n"))
    chunks: list[str] = []
    for section in (s.strip() for s in sections):
        if not section or _is_heading_only(section):
            continue
        chunks.extend(c.strip() for c in _split_long(section) if c.strip())
    return chunks


def document_path(name: str) -> Path:
    return config.KNOWLEDGE_DIR / name


@dataclass
class Chunk:
    document: str
    index: int  # position within its document
    text: str


@dataclass
class Hit:
    document: str
    index: int
    text: str
    score: float


def _fingerprint(names: tuple[str, ...]) -> tuple[tuple[str, int, int], ...]:
    """(name, mtime, size) per file — part of the cache key, so a document
    edited or re-uploaded from the UI is re-indexed on the next query
    instead of being served stale for the life of the process. A missing
    file fingerprints as (name, 0, 0) and simply contributes no chunks."""
    out = []
    for name in names:
        path = document_path(name)
        try:
            st = path.stat()
            out.append((name, st.st_mtime_ns, st.st_size))
        except OSError:
            out.append((name, 0, 0))
    return tuple(out)


def load_chunks(names: tuple[str, ...] | list[str]) -> list[Chunk]:
    chunks: list[Chunk] = []
    for name in names:
        path = document_path(name)
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        chunks.extend(Chunk(name, i, c) for i, c in enumerate(chunk_text(text)))
    return chunks


@lru_cache(maxsize=64)
def _index(fingerprint: tuple[tuple[str, int, int], ...]):
    chunks = load_chunks([name for name, _, _ in fingerprint])
    retriever = bm25s.BM25()
    if chunks:
        retriever.index([tokenize(c.text) for c in chunks], show_progress=False)
    return retriever, chunks


def search(names: tuple[str, ...] | list[str], query: str, top_k: int = 2) -> list[Hit]:
    """Best `top_k` chunks across `names` for `query`, highest score first.
    Chunks scoring 0 (no word in common with the query) are dropped rather
    than returned as "the best of nothing" — grounding a reply on a passage
    that has nothing to do with the question is worse than no grounding."""
    retriever, chunks = _index(_fingerprint(tuple(names)))
    query_tokens = tokenize(query)
    if not chunks or not query_tokens or top_k <= 0:
        return []
    k = min(top_k, len(chunks))
    results, scores = retriever.retrieve([query_tokens], k=k, show_progress=False)
    hits = []
    for i, score in zip(results[0].tolist(), scores[0].tolist()):
        if score <= 0:
            continue
        c = chunks[i]
        hits.append(Hit(c.document, c.index, c.text, round(float(score), 4)))
    return hits
