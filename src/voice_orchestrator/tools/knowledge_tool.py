"""RAG grounding, scoped per agent. Deliberately a lighter retrieval stack
than the Company Brain project (BM25 only, no dense/graph/rerank) — the
point here is the *integration pattern* ("an agent can be configured with
its own knowledge base and ground its replies in it"), not a second copy of
the hybrid-RAG pipeline. For a knowledge base big or ambiguous enough to
need dense retrieval and a reranker, swap this tool's internals for Company
Brain's `retrieval.py` — same interface, different engine.

Unlike the other tools, this one is always "triggered" when the agent has
any knowledge configured — it's grounding for every reply, not a discrete
action a specific utterance asks for.
"""
import re
from functools import lru_cache
from pathlib import Path

import bm25s

from .. import config
from ..agents.registry import AgentSpec
from ..state import CallSession
from .base import Tool, ToolResult


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zàèéìòù0-9]+", text.lower())


@lru_cache(maxsize=None)
def _load_index(knowledge_files: tuple[str, ...]):
    passages: list[str] = []
    for name in knowledge_files:
        path = config.KNOWLEDGE_DIR / name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        # Split on ## section headers (same reasoning as Company Brain: don't
        # cut a table/clause in half) — good enough for these small files.
        sections = re.split(r"\n(?=##\s)", text)
        passages.extend(s.strip() for s in sections if s.strip())

    retriever = bm25s.BM25()
    retriever.index([_tokenize(p) for p in passages], show_progress=False)
    return retriever, passages


class KnowledgeLookupTool(Tool):
    id = "knowledge_lookup"
    description = "Retrieves grounding passages from the agent's configured knowledge files."

    def should_trigger(self, agent: AgentSpec, utterance: str, session: CallSession) -> bool:
        return bool(agent.knowledge)

    def run(self, agent: AgentSpec, utterance: str, session: CallSession, top_k: int = 2) -> ToolResult:
        retriever, passages = _load_index(tuple(agent.knowledge))
        if not passages:
            return ToolResult(summary="No knowledge base configured for this agent.")

        query_tokens = _tokenize(utterance)
        k = min(top_k, len(passages))
        results, _scores = retriever.retrieve([query_tokens], k=k, show_progress=False)
        top_passages = [passages[i] for i in results[0].tolist()]

        joined = "\n\n---\n\n".join(top_passages)
        return ToolResult(
            summary=f"Grounding passages from {agent.name}'s knowledge base:\n\n{joined}",
            data={"passages": top_passages},
        )
