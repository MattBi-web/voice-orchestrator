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
        super().__init__(f"{name} è usato da: {', '.join(agents)}. Toglilo da quegli agenti prima di eliminarlo.")
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
        raise InvalidDocument(f"Nome documento non valido: {raw!r}")
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


def _info(session: Session, name: str, used_by: list[str]) -> DocumentInfo:
    path = knowledge.document_path(name)
    row = session.get(KnowledgeDocRow, name)
    if path.is_file():
        stat = path.stat()
        mtime = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
        chunks = len(knowledge.load_chunks([name]))
        return DocumentInfo(
            name, True, stat.st_size, chunks, row.source_type if row else "", row.source_url if row else "",
            row.updated_at if row and row.updated_at else mtime, used_by,
        )
    return DocumentInfo(name, False, 0, 0, row.source_type if row else "", row.source_url if row else "", "", used_by)


def list_documents(session: Session) -> list[DocumentInfo]:
    """Every document on disk, plus any name an agent references that has
    no file — listed as `exists=False`, because a typo'd or deleted file
    otherwise fails silently (the agent just never finds anything)."""
    used = _agents_using(session)
    names = sorted(set(_files()) | set(used))
    return [_info(session, n, used.get(n, [])) for n in names]


def get_document(session: Session, name: str) -> dict:
    path = knowledge.document_path(name)
    if not _NAME_RE.match(name) or not path.is_file():
        raise DocumentNotFound(name)
    info = _info(session, name, _agents_using(session).get(name, []))
    chunks = knowledge.load_chunks([name])
    return {
        **info.as_dict(),
        "content": path.read_text(encoding="utf-8", errors="replace"),
        "chunks": [{"index": c.index, "text": c.text} for c in chunks],
    }


def save_document(
    session: Session, name: str, content: str, source_type: str, source_url: str = "", overwrite: bool = False
) -> DocumentInfo:
    name = normalize_name(name)
    if not content.strip():
        raise InvalidDocument("Il documento è vuoto")
    data = content.encode("utf-8")
    if len(data) > MAX_DOCUMENT_BYTES:
        raise InvalidDocument(f"Documento troppo grande ({len(data)} byte, massimo {MAX_DOCUMENT_BYTES})")
    path = knowledge.document_path(name)
    if path.exists() and not overwrite:
        raise DocumentExists(f"Esiste già un documento {name!r}")
    if not knowledge.chunk_text(content):
        raise InvalidDocument("Il documento non contiene testo utilizzabile (solo titoli?)")

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{name}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)  # atomic: a reader never sees a half-written file

    row = session.get(KnowledgeDocRow, name) or KnowledgeDocRow(name=name)
    row.source_type = source_type
    row.source_url = source_url
    row.updated_at = datetime.now(timezone.utc).isoformat()
    session.add(row)
    session.flush()
    return _info(session, name, _agents_using(session).get(name, []))


def delete_document(session: Session, name: str) -> None:
    path = knowledge.document_path(name)
    if not _NAME_RE.match(name) or not path.is_file():
        raise DocumentNotFound(name)
    users = _agents_using(session).get(name, [])
    if users:
        raise DocumentInUse(name, users)
    path.unlink()
    row = session.get(KnowledgeDocRow, name)
    if row is not None:
        session.delete(row)
        session.flush()


# ---- web pages ----


def _is_private_host(host: str) -> bool:
    """True if `host` resolves to a loopback/private/link-local address.
    The builder fetches a URL from the *server*: without this, "add from
    URL" would read anything the server can reach on its own network."""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as exc:
        raise UrlFetchFailed(f"Host non risolvibile: {host}") from exc
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
        raise UrlFetchFailed("Serve un URL http:// o https:// completo")

    def _guard(request: httpx.Request) -> None:
        # Runs before every request, redirects included: a public URL that
        # redirects to a private address is refused at that hop.
        if _is_private_host(request.url.host):
            raise UrlFetchFailed("Indirizzi locali o di rete privata non sono ammessi")

    try:
        with httpx.Client(
            transport=_url_transport,
            timeout=URL_TIMEOUT_SECONDS,
            follow_redirects=True,
            event_hooks={"request": [_guard]},
        ) as client:
            response = client.get(url.strip(), headers={"User-Agent": "voice-orchestrator-kb/1.0"})
    except httpx.HTTPError as exc:
        raise UrlFetchFailed(f"Impossibile scaricare la pagina: {exc}") from exc
    if response.status_code >= 400:
        raise UrlFetchFailed(f"La pagina ha risposto {response.status_code}")
    if len(response.content) > MAX_URL_BYTES:
        raise UrlFetchFailed(f"Pagina troppo grande ({len(response.content)} byte)")

    ctype = response.headers.get("content-type", "").lower()
    if "html" in ctype or (not ctype and "<html" in response.text[:500].lower()):
        title, text = html_to_text(response.text)
    elif ctype.startswith("text/") or "markdown" in ctype or not ctype:
        title, text = "", response.text
    else:
        raise UrlFetchFailed(f"Tipo di contenuto non supportato: {ctype or 'sconosciuto'} (solo pagine HTML o testo)")
    if not text.strip():
        raise UrlFetchFailed("Nessun testo leggibile nella pagina")

    base = title or (parsed.hostname + parsed.path)
    slug = re.sub(r"[^A-Za-z0-9]+", "_", base).strip("_").lower()[:60] or "pagina"
    heading = f"# {title}\n\nFonte: {url.strip()}\n\n" if title else f"Fonte: {url.strip()}\n\n"
    return f"{slug}.md", heading + text
