"""The agent-builder's FastAPI backend — CRUD over the SQLite-backed agent
family (see db.py/models.py/repository.py) plus a `/api/test/route` endpoint
that runs a real utterance through the *actual* router/orchestrator
(routing.router.route / orchestrator.handle_turn), not a simulated stand-in,
so the frontend's "try it" box shows exactly what a real call would do.

Run it with:
    uvicorn voice_orchestrator.webapi.app:app --reload --port 8000

CORS is wide open to localhost dev-server origins only — this is a local
development tool today (see README), not something meant to be exposed on
the public internet without adding real authentication first.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..llm import FakeProvider
from ..orchestrator import handle_turn
from ..state import CallSession
from ..tools import REGISTRY
from . import repository, seed, voice_token
from .db import get_session
from .models import AgentRow
from .repository import AgentInput
from .schemas import (
    AgentIn,
    AgentOut,
    AgentUpdate,
    TestRouteRequest,
    TestRouteResponse,
    build_agent_out_tree,
    row_to_out,
)


def _startup_seed() -> None:
    # Plain helper kept separate from the lifespan context manager below so
    # the one-time seed uses the exact same get_session()/commit path every
    # other request does, rather than a bespoke engine call.
    gen = get_session()
    session = next(gen)
    try:
        seed.seed_if_empty(session)
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    _startup_seed()
    yield


app = FastAPI(title="voice-orchestrator agent builder", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/tools")
def list_tools() -> dict:
    return {"tools": sorted(REGISTRY)}


@app.get("/api/voice/status")
def voice_status() -> dict:
    """Whether LIVEKIT_URL/API_KEY/API_SECRET are set — the frontend uses
    this to grey out the live voice console with a helpful message instead
    of letting a click fail with an opaque network error."""
    return {"configured": voice_token.is_configured()}


@app.post("/api/voice/token")
def voice_token_endpoint() -> dict:
    """Issues one short-lived LiveKit room token per call, exactly what the
    hosted Agents Playground's own backend does — see voice_token.py's
    docstring for why a running worker, not this endpoint, is what actually
    answers the call."""
    if not voice_token.is_configured():
        raise HTTPException(
            400,
            "LIVEKIT_URL/LIVEKIT_API_KEY/LIVEKIT_API_SECRET non sono impostate "
            "lato backend — vedi la sezione 'Voice layer' del README.",
        )
    return voice_token.mint()


@app.get("/api/agents")
def get_agent_tree(session: Session = Depends(get_session)) -> dict:
    rows = session.scalars(select(AgentRow).order_by(AgentRow.position)).all()
    return {"root": build_agent_out_tree(rows)}


@app.get("/api/agents/{agent_id}", response_model=AgentOut)
def get_agent(agent_id: str, session: Session = Depends(get_session)) -> AgentOut:
    try:
        row = repository.get_row(session, agent_id)
    except repository.AgentNotFound:
        raise HTTPException(404, f"No agent with id={agent_id!r}")
    child_rows = session.scalars(select(AgentRow).where(AgentRow.parent_id == agent_id)).all()
    out = row_to_out(row)
    out.children_ids = [r.id for r in child_rows]
    return out


@app.post("/api/agents", response_model=AgentOut, status_code=201)
def create_agent(body: AgentIn, session: Session = Depends(get_session)) -> AgentOut:
    data = AgentInput(
        id=body.id,
        parent_id=body.parent_id,
        name=body.name,
        description=body.description,
        system_prompt=body.system_prompt,
        eligibility=body.eligibility,
        voice=body.voice,
        triggers=body.triggers,
        tools=[t.model_dump() for t in body.tools],
        knowledge=body.knowledge,
    )
    try:
        row = repository.create_agent(session, data)
    except repository.AgentIdTaken:
        raise HTTPException(409, f"Agent id={body.id!r} already exists")
    except repository.ParentNotFound as exc:
        raise HTTPException(400, str(exc))
    return row_to_out(row)


@app.put("/api/agents/{agent_id}", response_model=AgentOut)
def update_agent(agent_id: str, body: AgentUpdate, session: Session = Depends(get_session)) -> AgentOut:
    data = AgentInput(
        id=agent_id,
        parent_id=None,  # not used by update_agent; reparenting isn't supported in v1
        name=body.name,
        description=body.description,
        system_prompt=body.system_prompt,
        eligibility=body.eligibility,
        voice=body.voice,
        triggers=body.triggers,
        tools=[t.model_dump() for t in body.tools],
        knowledge=body.knowledge,
    )
    try:
        row = repository.update_agent(session, agent_id, data)
    except repository.AgentNotFound:
        raise HTTPException(404, f"No agent with id={agent_id!r}")
    return row_to_out(row)


@app.delete("/api/agents/{agent_id}", status_code=204)
def delete_agent(agent_id: str, session: Session = Depends(get_session)) -> None:
    try:
        repository.delete_agent(session, agent_id)
    except repository.AgentNotFound:
        raise HTTPException(404, f"No agent with id={agent_id!r}")
    except repository.CannotDeleteRoot:
        raise HTTPException(400, "Cannot delete the root (router) agent")
    except repository.HasChildren:
        raise HTTPException(409, "Delete this agent's children first")


@app.post("/api/test/route", response_model=TestRouteResponse)
def test_route(body: TestRouteRequest, session: Session = Depends(get_session)) -> TestRouteResponse:
    """Builds the DB-backed family into a real AgentSpec tree and runs the
    utterance through the *actual* orchestrator with FakeProvider — the
    same zero-API-key path `voice-orchestrator chat`/`route` use, so this
    "try it" box never needs a real LLM key to be useful for checking that
    routing/tools behave as the editor intended."""
    root = repository.build_tree(session)
    if root is None:
        raise HTTPException(400, "No agents yet — create a root agent first")

    start = root.find(body.start_agent_id) if body.start_agent_id else root
    if start is None:
        raise HTTPException(404, f"No agent with id={body.start_agent_id!r}")

    call_session = CallSession(call_id="webapi-test", channel=body.channel, slots=dict(body.slots))
    call_session.agent_path = [a.id for a in _path_to(root, start.id)]

    result = handle_turn(call_session, root, body.utterance, FakeProvider())
    return TestRouteResponse(
        agent_id=result.agent.id,
        agent_name=result.agent.name,
        resolved_by=result.routing.resolved_by,
        eligible_agents=result.routing.eligible_agents,
        handed_off=result.handed_off,
        reply=result.reply,
        tool_ids_used=result.tool_ids_used,
    )


def _path_to(root, target_id: str) -> list:
    """root -> ... -> target_id, the shape CallSession.agent_path expects —
    found by depth-first search since AgentSpec itself has no parent
    pointer (children-only, same as agents/registry.py everywhere else)."""
    if root.id == target_id:
        return [root]
    for child in root.children:
        sub = _path_to(child, target_id)
        if sub:
            return [root, *sub]
    return []
