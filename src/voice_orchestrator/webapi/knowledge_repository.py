"""Knowledge documents from the agent builder (blocco 5): list, read, add
(pasted text, an uploaded file, or a web page), delete — on the files in
`config.KNOWLEDGE_DIR` that `knowledge.py` reads, plus a `KnowledgeDocRow`
per document recording where it came from.

Uploads arrive as text: the browser reads the file and sends its content as
JSON, so the API needs no multipart dependency, and only text formats
(`.md`, `.txt`) are accepted. PDF/DOCX extraction is a deliberate gap, not
an oversight — see docs/ROADMAP.md.
"""
from __future__ import annotations

import ipaddress
import os
import re
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config, knowledge
from .models import AgentRow, KnowledgeDocRow

MAX_DOCUMENT_BYTES = 1_000_000
MAX_URL_BYTES = 3_000_000
URL_TIMEOUT_SECONDS = 15.0

# Tests inject an httpx.MockTransport here, the same way tools/webhook_tool.py's
# tests do, so nothing in the suite touches the network.
_url_transport: httpx.BaseTransport | None = None

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,80}\.(md|txt)$")


class InvalidDocument(ValueError):
    pass


class DocumentExists(ValueError):
    pass


class DocumentNotFound(ValueError):
    pass


class DocumentInUse(ValueError):
    def __init__(self, name: str, agents: list[str]):
        super().__init__(f"{name} is used by {', '.join(agents)}. Remove it from those agents first.")
        self.agents = agents


class UrlFetchFailed(ValueError):
    pass


def normalize_name(raw: str) -> str:
    """A safe file name: spaces → `_`, anything outside [A-Za-z0-9_.-]
    dropped, `.md` appended when there's no allowed extension. Anything that
    still isn't a plain file name (empty, a path) is rejected."""
    name = re.sub(r"\s+", "_", raw.strip())
    name = re.sub(r"[^A-Za-z0-9_.-]", "", name).strip(".")
    if not name.lower().endswith(knowledge.ALLOWED_SUFFIXES):
        name = f"{name}.md"
    if ".." in name or not _NAME_RE.match(name):
        raise InvalidDocument(f"Not a valid document name: {raw!r}")
    return name


def _agents_using(session: Session) -> dict[str, list[str]]:
    used: dict[str, list[str]] = {}
    for row in session.scalars(select(AgentRow).order_by(AgentRow.id)).all():
        for name in row.knowledge:
            used.setdefault(name, []).append(row.id)
    return used


def _files() -> list[str]:
    if not config.KNOWLEDGE_DIR.is_dir():
        return []
    return sorted(
        p.name for p in config.KNOWLEDGE_DIR.iterdir() if p.is_file() and p.suffix.lower() in knowledge.ALLOWED_SUFFIXES
    )


# Where a document's text lives: a file in data/knowledge/ (default mode) or
# KnowledgeDocRow.content (shared mode, blocco 6 — the worker is another
# machine). These helpers are the only place that knows; everything below
# goes through them, always with the request's own session, so a save is
# visible to the rest of the same request before it commits.


def _stored_names(session: Session) -> list[str]:
    if config.shared_mode():
        rows = session.scalars(select(KnowledgeDocRow).where(KnowledgeDocRow.content != "")).all()
        return sorted(r.name for r in rows)
    return _files()


def _read_text(session: Session, name: str) -> str | None:
    if not _NAME_RE.match(name):
        return None
    if config.shared_mode():
        row = session.get(KnowledgeDocRow, name)
        return row.content if row and row.content else None
    path = knowledge.document_path(name)
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else None


def _write_text(session: Session, name: str, content: str) -> None:
    if config.shared_mode():
        row = session.get(KnowledgeDocRow, name) or KnowledgeDocRow(name=name)
        row.content = content
        session.add(row)
        return
    path = knowledge.document_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{name}.tmp")
    tmp.write_bytes(content.encode("utf-8"))
    os.replace(tmp, path)  # atomic: a reader never sees a half-written file


def _file_mtime(name: str) -> str:
    path = knowledge.document_path(name)
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    except OSError:
        return ""


@dataclass
class DocumentInfo:
    name: str
    exists: bool
    size_bytes: int
    chunk_count: int
    source_type: str
    source_url: str
    updated_at: str
    used_by: list[str]

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def _info(session: Session, name: str, used_by: list[str], text: str | None = None) -> DocumentInfo:
    row = session.get(KnowledgeDocRow, name)
    text = text if text is not None else _read_text(session, name)
    source_type = row.source_type if row else ""
    source_url = row.source_url if row else ""
    if text is None:
        return DocumentInfo(name, False, 0, 0, source_type, source_url, "", used_by)
    updated = row.updated_at if row and row.updated_at else _file_mtime(name)
    return DocumentInfo(
        name, True, len(text.encode("utf-8")), len(knowledge.chunk_text(text)), source_type, source_url, updated, used_by
    )


def list_documents(session: Session) -> list[DocumentInfo]:
    """Every stored document, plus any name an agent references that has
    none — listed as `exists=False`, because a typo'd or deleted document
    otherwise fails silently (the agent just never finds anything)."""
    used = _agents_using(session)
    names = sorted(set(_stored_names(session)) | set(used))
    return [_info(session, n, used.get(n, [])) for n in names]


def get_document(session: Session, name: str) -> dict:
    text = _read_text(session, name)
    if text is None:
        raise DocumentNotFound(name)
    info = _info(session, name, _agents_using(session).get(name, []), text=text)
    return {
        **info.as_dict(),
        "content": text,
        "chunks": [{"index": i, "text": c} for i, c in enumerate(knowledge.chunk_text(text))],
    }


def save_document(
    session: Session, name: str, content: str, source_type: str, source_url: str = "", overwrite: bool = False
) -> DocumentInfo:
    name = normalize_name(name)
    if not content.strip():
        raise InvalidDocument("The document is empty")
    data = content.encode("utf-8")
    if len(data) > MAX_DOCUMENT_BYTES:
        raise InvalidDocument(f"Document too large ({len(data)} bytes, limit {MAX_DOCUMENT_BYTES})")
    if _read_text(session, name) is not None and not overwrite:
        raise DocumentExists(f"A document named {name!r} already exists")
    if not knowledge.chunk_text(content):
        raise InvalidDocument("The document has no usable text (only headings?)")

    _write_text(session, name, content)
    row = session.get(KnowledgeDocRow, name) or KnowledgeDocRow(name=name)
    row.source_type = source_type
    row.source_url = source_url
    row.updated_at = datetime.now(timezone.utc).isoformat()
    session.add(row)
    session.flush()
    return _info(session, name, _agents_using(session).get(name, []), text=content)


def delete_document(session: Session, name: str) -> None:
    if _read_text(session, name) is None:
        raise DocumentNotFound(name)
    users = _agents_using(session).get(name, [])
    if users:
        raise DocumentInUse(name, users)
    if not config.shared_mode():
        knowledge.document_path(name).unlink()
    row = session.get(KnowledgeDocRow, name)
    if row is not None:
        session.delete(row)
        session.flush()


def seed_from_files(session: Session) -> int:
    """Shared mode: copy the bundled documents in data/knowledge/ into the
    database the first time it has none, so a fresh deploy starts with the
    demo family's knowledge — the same one-time seed agents.yaml gets.
    Returns how many were copied (0 if the database already had documents,
    or outside shared mode)."""
    if not config.shared_mode() or _stored_names(session):
        return 0
    copied = 0
    for name in _files():
        text = knowledge.document_path(name).read_text(encoding="utf-8", errors="replace")
        if not text.strip():
            continue
        row = session.get(KnowledgeDocRow, name) or KnowledgeDocRow(name=name)
        row.content, row.source_type, row.updated_at = text, "", datetime.now(timezone.utc).isoformat()
        session.add(row)
        copied += 1
    session.flush()
    return copied


# ---- web pages ----


def _is_private_host(host: str) -> bool:
    """True if `host` resolves to a loopback/private/link-local address.
    The builder fetches a URL from the *server*: without this, "add from
    URL" would read anything the server can reach on its own network."""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as exc:
        raise UrlFetchFailed(f"Can't resolve host: {host}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return True
    return False


_SKIP_TAGS = {"script", "style", "noscript", "nav", "footer", "header", "svg", "form", "aside", "template"}
_BLOCK_TAGS = {"p", "div", "section", "article", "main", "br", "tr", "table", "ul", "ol", "blockquote", "pre"}
_HEADINGS = {"h1": "# ", "h2": "## ", "h3": "## ", "h4": "## ", "h5": "## ", "h6": "## "}


class _TextExtractor(HTMLParser):
    """Readable text out of an HTML page, standard library only: skips
    scripts/navigation, turns headings into markdown headings (so
    knowledge.chunk_text() splits the page on its own sections) and list
    items into "- " lines. Not a readability engine — a cluttered page
    brings some clutter with it, which the chunk preview makes visible."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif self._skip:
            return
        elif tag in _HEADINGS:
            self.parts.append("\n\n" + _HEADINGS[tag])
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n\n")

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
        elif tag == "title":
            self._in_title = False
        elif not self._skip and (tag in _HEADINGS or tag in _BLOCK_TAGS):
            self.parts.append("\n\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(re.sub(r"\s+", " ", data))

    def text(self) -> str:
        raw = "".join(self.parts)
        lines = [line.strip() for line in raw.splitlines()]
        out = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
        # A heading marker left with nothing after it (an empty <h2>) is noise.
        return re.sub(r"^#{1,2}\s*$", "", out, flags=re.MULTILINE).strip()


def html_to_text(html: str) -> tuple[str, str]:
    """(title, text)."""
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    return parser.title.strip(), parser.text()


def fetch_url(url: str) -> tuple[str, str]:
    """(suggested document name, extracted text) for a web page or a plain
    text/markdown file. Needs outbound internet from the server, like the
    webhook demo (D14)."""
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise UrlFetchFailed("Enter a full http:// or https:// address")

    def _guard(request: httpx.Request) -> None:
        # Runs before every request, redirects included: a public URL that
        # redirects to a private address is refused at that hop.
        if _is_private_host(request.url.host):
            raise UrlFetchFailed("Local and private network addresses are not allowed")

    try:
        with httpx.Client(
            transport=_url_transport,
            timeout=URL_TIMEOUT_SECONDS,
            follow_redirects=True,
            event_hooks={"request": [_guard]},
        ) as client:
            response = client.get(url.strip(), headers={"User-Agent": "voice-orchestrator-kb/1.0"})
    except httpx.HTTPError as exc:
        raise UrlFetchFailed(f"Couldn't download the page: {exc}") from exc
    if response.status_code >= 400:
        raise UrlFetchFailed(f"The page answered with status {response.status_code}")
    if len(response.content) > MAX_URL_BYTES:
        raise UrlFetchFailed(f"Page too large ({len(response.content)} bytes)")

    ctype = response.headers.get("content-type", "").lower()
    if "html" in ctype or (not ctype and "<html" in response.text[:500].lower()):
        title, text = html_to_text(response.text)
    elif ctype.startswith("text/") or "markdown" in ctype or not ctype:
        title, text = "", response.text
    else:
        raise UrlFetchFailed(f"Unsupported content type: {ctype or 'unknown'} (only HTML pages and plain text)")
    if not text.strip():
        raise UrlFetchFailed("No readable text on the page")

    base = title or (parsed.hostname + parsed.path)
    slug = re.sub(r"[^A-Za-z0-9]+", "_", base).strip("_").lower()[:60] or "pagina"
    heading = f"# {title}\n\nSource: {url.strip()}\n\n" if title else f"Source: {url.strip()}\n\n"
    return f"{slug}.md", heading + text
