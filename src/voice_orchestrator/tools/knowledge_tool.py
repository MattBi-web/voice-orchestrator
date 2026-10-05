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
from .. import knowledge
from ..agents.registry import AgentSpec
from ..state import CallSession
from .base import Tool, ToolResult


class KnowledgeLookupTool(Tool):
    id = "knowledge_lookup"
    description = "Retrieves grounding passages from the agent's configured knowledge files."

    def should_trigger(self, agent: AgentSpec, utterance: str, session: CallSession) -> bool:
        return bool(agent.knowledge)

    def run(self, agent: AgentSpec, utterance: str, session: CallSession, top_k: int = 2) -> ToolResult:
        # Chunking and search live in knowledge.py (blocco 5), shared with the
        # agent builder's preview, so what the editor previews is what the
        # agent gets here.
        hits = knowledge.search(tuple(agent.knowledge), utterance, top_k=top_k)
        if not hits:
            # Nothing in the agent's documents shares a word with the
            # utterance. Say so to the model; say nothing to the caller (an
            # empty caller_text adds nothing to FakeProvider's reply), rather
            # than reading out an unrelated passage as if it answered.
            return ToolResult(
                summary="The knowledge base has no passage relevant to this utterance: don't invent one.",
                caller_text="",
                data={"passages": [], "sources": []},
            )

        top_passages = [h.text for h in hits]
        joined = "\n\n---\n\n".join(top_passages)
        return ToolResult(
            summary=f"Grounding passages from {agent.name}'s knowledge base:\n\n{joined}",
            # FakeProvider has no model to paraphrase with: the single best
            # passage, verbatim, is the honest stand-in for a grounded answer.
            caller_text=top_passages[0],
            data={
                "passages": top_passages,
                "sources": [{"document": h.document, "chunk": h.index, "score": h.score} for h in hits],
            },
        )
