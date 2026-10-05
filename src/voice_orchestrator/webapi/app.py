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

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import analysis, call_events, call_log, config, knowledge
from ..agents.registry import save_family
from ..llm import FakeProvider, get_provider, get_provider_for_agent
from ..orchestrator import handle_turn
from ..state import CallSession
from ..tools import REGISTRY
from ..tools import webhook_log as webhook_log_module
from . import analysis_repository, auth, knowledge_repository, mcp_repository, mcp_sync, repository, seed, test_conversations, voice_token, webhook_repository, webhook_sync
from .db import get_session
from .mcp_repository import McpServerInput
from .models import AgentRow
from .repository import AgentInput
from .schemas import (
    AgentIn,
    AgentLayoutUpdate,
    AgentOut,
    AgentReparentRequest,
    AgentUpdate,
    AnalysisConfigSchema,
    CriterionSchema,
    DataItemSchema,
    KnowledgeDocIn,
    KnowledgeSearchIn,
    KnowledgeUrlIn,
    McpServerIn,
    McpServerOut,
    TestRouteRequest,
    TestRouteResponse,
    WebhookExecutionOut,
    WebhookToolIn,
    WebhookToolOut,
    build_agent_out_tree,
    mcp_row_to_out,
    row_to_out,
    webhook_row_to_out,
)
from .webhook_repository import WebhookToolInput


def _startup_seed() -> None:
    # Plain helper kept separate from the lifespan context manager below so
    # the one-time seed uses the exact same get_session()/commit path every
    # other request does, rather than a bespoke engine call.
    gen = get_session()
    session = next(gen)
    try:
        seed.seed_if_empty(session)
        seed.seed_mcp_if_empty(session)
        seed.seed_webhook_tools_if_empty(session)
        seed.seed_analysis_if_empty(session)
        knowledge_repository.seed_from_files(session)  # shared mode only; no-op otherwise
        # Always re-sync, even when nothing was just seeded: this is also
        # what makes the registry correct across a plain server restart,
        # when the DB already holds rows from a previous run.
        mcp_sync.sync_registry_from_db(session)
        webhook_sync.sync_registry_from_db(session)
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


@app.middleware("http")
async def owner_only_writes(request: Request, call_next):
    """Blocco 6: with VOICE_ORCH_OWNER_PASSWORD set, every API request that
    could change something needs the owner's session (see auth.py for the
    few visitor exceptions). One check here instead of one per route, so a
    route added later is protected by default rather than by remembering."""
    path = request.url.path
    if path.startswith("/api/") and not auth.visitor_may(request.method, path) and not auth.is_owner(request):
        return JSONResponse({"detail": "Read-only demo: sign in as the owner to make changes."}, status_code=401)
    return await call_next(request)


class LoginIn(BaseModel):
    password: str


@app.get("/api/auth/me")
def auth_me(request: Request) -> dict:
    return {"auth_required": auth.auth_required(), "owner": auth.is_owner(request)}


@app.post("/api/auth/login")
def auth_login(body: LoginIn, request: Request, response: Response) -> dict:
    if not auth.auth_required():
        return {"auth_required": False, "owner": True}
    if not auth.check_password(body.password):
        raise HTTPException(401, "Wrong password")
    response.set_cookie(
        auth.COOKIE_NAME,
        auth.make_token(),
        max_age=auth.SESSION_SECONDS,
        httponly=True,
        samesite="lax",
        # Behind Render's TLS proxy the app itself sees plain http.
        secure=request.headers.get("x-forwarded-proto", request.url.scheme) == "https",
    )
    return {"auth_required": True, "owner": True}


@app.post("/api/auth/logout")
def auth_logout(response: Response) -> dict:
    response.delete_cookie(auth.COOKIE_NAME)
    return {"auth_required": auth.auth_required(), "owner": not auth.auth_required()}


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/tools")
def list_tools() -> dict:
    return {"tools": sorted(REGISTRY)}


@app.get("/api/mcp-servers")
def list_mcp_servers(session: Session = Depends(get_session)) -> dict:
    rows = mcp_repository.list_servers(session)
    return {"servers": [mcp_row_to_out(r) for r in rows]}


@app.post("/api/mcp-servers", response_model=McpServerOut, status_code=201)
def create_mcp_server(body: McpServerIn, session: Session = Depends(get_session)) -> McpServerOut:
    try:
        row = mcp_repository.create_server(
            session, McpServerInput(name=body.name, command=body.command, args=body.args)
        )
    except mcp_repository.McpServerNameTaken:
        raise HTTPException(409, f"MCP server name={body.name!r} already exists")
    # Sync before the response goes out, not after: a client that creates a
    # server and immediately tests a route against it (see
    # test_webapi.py's end-to-end sync test) must see it live right away,
    # with no restart and no second request in between.
    mcp_sync.sync_registry_from_db(session)
    return mcp_row_to_out(row)


@app.put("/api/mcp-servers/{name}", response_model=McpServerOut)
def update_mcp_server(name: str, body: McpServerIn, session: Session = Depends(get_session)) -> McpServerOut:
    try:
        row = mcp_repository.update_server(session, name, McpServerInput(name=name, command=body.command, args=body.args))
    except mcp_repository.McpServerNotFound:
        raise HTTPException(404, f"No MCP server named {name!r}")
    mcp_sync.sync_registry_from_db(session)
    return mcp_row_to_out(row)


@app.delete("/api/mcp-servers/{name}", status_code=204)
def delete_mcp_server(name: str, session: Session = Depends(get_session)) -> None:
    tool_id = f"mcp:{name}"
    if tool_id in repository.list_tool_ids_in_use(session):
        raise HTTPException(409, f"{tool_id!r} is still attached to one or more agents — detach it first")
    try:
        mcp_repository.delete_server(session, name)
    except mcp_repository.McpServerNotFound:
        raise HTTPException(404, f"No MCP server named {name!r}")
    mcp_sync.sync_registry_from_db(session)


@app.get("/api/webhook-tools")
def list_webhook_tools(session: Session = Depends(get_session)) -> dict:
    rows = webhook_repository.list_tools(session)
    return {"tools": [webhook_row_to_out(r) for r in rows]}


@app.post("/api/webhook-tools", response_model=WebhookToolOut, status_code=201)
def create_webhook_tool(body: WebhookToolIn, session: Session = Depends(get_session)) -> WebhookToolOut:
    data = WebhookToolInput(
        name=body.name,
        description=body.description,
        url=body.url,
        method=body.method,
        headers=body.headers,
        params=[p.model_dump() for p in body.params],
        triggers=body.triggers,
        timeout_seconds=body.timeout_seconds,
    )
    try:
        row = webhook_repository.create_tool(session, data)
    except webhook_repository.WebhookToolNameTaken:
        raise HTTPException(409, f"Webhook tool name={body.name!r} already exists")
    # Sync before the response goes out, not after — same reasoning as the
    # MCP server endpoints above: a client that creates a tool and
    # immediately tests a route against it must see it live right away.
    webhook_sync.sync_registry_from_db(session)
    return webhook_row_to_out(row)


@app.put("/api/webhook-tools/{name}", response_model=WebhookToolOut)
def update_webhook_tool(name: str, body: WebhookToolIn, session: Session = Depends(get_session)) -> WebhookToolOut:
    data = WebhookToolInput(
        name=name,
        description=body.description,
        url=body.url,
        method=body.method,
        headers=body.headers,
        params=[p.model_dump() for p in body.params],
        triggers=body.triggers,
        timeout_seconds=body.timeout_seconds,
    )
    try:
        row = webhook_repository.update_tool(session, name, data)
    except webhook_repository.WebhookToolNotFound:
        raise HTTPException(404, f"No webhook tool named {name!r}")
    webhook_sync.sync_registry_from_db(session)
    return webhook_row_to_out(row)


@app.delete("/api/webhook-tools/{name}", status_code=204)
def delete_webhook_tool(name: str, session: Session = Depends(get_session)) -> None:
    tool_id = f"webhook:{name}"
    if tool_id in repository.list_tool_ids_in_use(session):
        raise HTTPException(409, f"{tool_id!r} is still attached to one or more agents — detach it first")
    try:
        webhook_repository.delete_tool(session, name)
    except webhook_repository.WebhookToolNotFound:
        raise HTTPException(404, f"No webhook tool named {name!r}")
    webhook_sync.sync_registry_from_db(session)


@app.get("/api/webhook-tools/executions")
def list_webhook_executions(limit: int = 50) -> dict:
    """Newest first, straight off webhook_log.jsonl — the "log esecuzioni
    tool" tab's data source. Plain JSONL read, same shape as GET /api/calls."""
    records = webhook_log_module.read_all()
    records = list(reversed(records))[: max(limit, 0)]
    return {"executions": [WebhookExecutionOut(**r.as_dict()) for r in records]}


# ---- blocco 5: knowledge base ----


@app.get("/api/knowledge")
def list_knowledge(session: Session = Depends(get_session)) -> dict:
    return {
        "documents": [d.as_dict() for d in knowledge_repository.list_documents(session)],
        "max_chunk_chars": knowledge.MAX_CHUNK_CHARS,
    }


@app.post("/api/knowledge/search")
def search_knowledge(body: KnowledgeSearchIn, session: Session = Depends(get_session)) -> dict:
    """Preview: the chunks a question retrieves, with their BM25 scores.
    Same `knowledge.search()` the `knowledge_lookup` tool calls mid-call —
    with `agent_id`, over that agent's own documents, so this is exactly the
    grounding that agent would get (it uses the top 2; the preview can show
    more, to see what just missed)."""
    names = list(body.documents)
    if body.agent_id:
        root = repository.build_tree(session)
        agent = root.find(body.agent_id) if root else None
        if agent is None:
            raise HTTPException(404, f"No agent with id={body.agent_id!r}")
        names = list(agent.knowledge)
    if not names:
        names = [d.name for d in knowledge_repository.list_documents(session) if d.exists]
    hits = knowledge.search(tuple(names), body.query, top_k=body.top_k)
    return {"documents": names, "hits": [h.__dict__ for h in hits]}


@app.post("/api/knowledge/from-url", status_code=201)
def add_knowledge_from_url(body: KnowledgeUrlIn, session: Session = Depends(get_session)) -> dict:
    try:
        suggested, text = knowledge_repository.fetch_url(body.url)
        info = knowledge_repository.save_document(
            session, body.name or suggested, text, source_type="url", source_url=body.url.strip(), overwrite=body.overwrite
        )
    except knowledge_repository.UrlFetchFailed as exc:
        raise HTTPException(502, str(exc))
    except knowledge_repository.DocumentExists as exc:
        raise HTTPException(409, str(exc))
    except knowledge_repository.InvalidDocument as exc:
        raise HTTPException(400, str(exc))
    return info.as_dict()


@app.post("/api/knowledge", status_code=201)
def add_knowledge(body: KnowledgeDocIn, session: Session = Depends(get_session)) -> dict:
    try:
        info = knowledge_repository.save_document(
            session, body.name, body.content, source_type=body.source_type, overwrite=body.overwrite
        )
    except knowledge_repository.DocumentExists as exc:
        raise HTTPException(409, str(exc))
    except knowledge_repository.InvalidDocument as exc:
        raise HTTPException(400, str(exc))
    return info.as_dict()


@app.get("/api/knowledge/{name}")
def get_knowledge(name: str, session: Session = Depends(get_session)) -> dict:
    try:
        return knowledge_repository.get_document(session, name)
    except knowledge_repository.DocumentNotFound:
        raise HTTPException(404, f"No document named {name!r}")


@app.delete("/api/knowledge/{name}", status_code=204)
def delete_knowledge(name: str, session: Session = Depends(get_session)) -> None:
    try:
        knowledge_repository.delete_document(session, name)
    except knowledge_repository.DocumentNotFound:
        raise HTTPException(404, f"No document named {name!r}")
    except knowledge_repository.DocumentInUse as exc:
        raise HTTPException(409, str(exc))


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
        triggers=body.triggers,
        tools=[t.model_dump() for t in body.tools],
        knowledge=body.knowledge,
        first_message=body.first_message,
        llm_provider=body.llm_provider,
        llm_model=body.llm_model,
        llm_temperature=body.llm_temperature,
        voice_id=body.voice_id,
        voice_stability=body.voice_stability,
        voice_speed=body.voice_speed,
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
        triggers=body.triggers,
        tools=[t.model_dump() for t in body.tools],
        knowledge=body.knowledge,
        first_message=body.first_message,
        llm_provider=body.llm_provider,
        llm_model=body.llm_model,
        llm_temperature=body.llm_temperature,
        voice_id=body.voice_id,
        voice_stability=body.voice_stability,
        voice_speed=body.voice_speed,
    )
    try:
        row = repository.update_agent(session, agent_id, data)
    except repository.AgentNotFound:
        raise HTTPException(404, f"No agent with id={agent_id!r}")
    return row_to_out(row)


@app.patch("/api/agents/{agent_id}/layout", response_model=AgentOut)
def update_agent_layout(
    agent_id: str, body: AgentLayoutUpdate, session: Session = Depends(get_session)
) -> AgentOut:
    """Blocco 4: the graph view calls this after a drag, instead of a full
    PUT, so repositioning a node is one small, frequent write rather than
    resending the whole agent form."""
    try:
        row = repository.update_layout(session, agent_id, body.layout_x, body.layout_y)
    except repository.AgentNotFound:
        raise HTTPException(404, f"No agent with id={agent_id!r}")
    return row_to_out(row)


@app.patch("/api/agents/{agent_id}/parent", response_model=AgentOut)
def reparent_agent(
    agent_id: str, body: AgentReparentRequest, session: Session = Depends(get_session)
) -> AgentOut:
    """D13: moves an agent (and its subtree) under a different parent —
    what the graph view's drag-a-node-onto-another-node does."""
    try:
        row = repository.reparent_agent(session, agent_id, body.parent_id)
    except repository.AgentNotFound:
        raise HTTPException(404, f"No agent with id={agent_id!r}")
    except repository.CannotReparentRoot:
        raise HTTPException(400, "Cannot reparent the root (router) agent")
    except repository.ParentNotFound as exc:
        raise HTTPException(400, str(exc))
    except repository.WouldCreateCycle as exc:
        raise HTTPException(409, str(exc))
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


@app.post("/api/agents/export")
def export_agents(session: Session = Depends(get_session)) -> dict:
    """Writes the DB-backed family (whatever the builder currently holds)
    back to `config/agents.yaml`, using the exact same `save_family()` the
    CLI's own `agents add`/`agents remove` commands already use — this isn't
    a new serializer, just a new caller of one that's shipped since the
    first commit.

    An explicit action, not something that runs on every save: the two
    sources of truth are deliberately kept separate day to day (see
    docs/ROADMAP.md's decision log) — this is the escape hatch for "I want
    what I built in the browser to be what `chat`/the voice worker/tests
    actually use," not a silent sync. It overwrites a file tracked in git,
    so the frontend confirms before calling this.

    Nothing needs restarting afterwards: `load_family()` is called fresh by
    every `chat`/`route` invocation and by the voice worker's
    `new_voice_bridge()` on every new call — so the very next one already
    sees this export, even against an already-running worker process."""
    root = repository.build_tree(session)
    if root is None:
        raise HTTPException(400, "No agents yet — nothing to export")
    save_family(root, config.AGENTS_FILE)
    agent_count = sum(1 for _ in root.iter_subtree())
    return {"path": str(config.AGENTS_FILE), "agent_count": agent_count}


@app.get("/api/llm/status")
def llm_status() -> dict:
    """Which provider VOICE_ORCH_PROVIDER asks for, and which one actually
    resolves. They differ when a real provider is requested but can't be
    built (missing key, missing SDK): `get_provider()` then falls back to
    FakeProvider silently, and the try-it box should say so rather than let
    the user believe they're testing the real model (D3)."""
    resolved = type(get_provider()).__name__
    return {"requested": config.PROVIDER, "resolved": resolved, "real": resolved != "FakeProvider"}


@app.post("/api/test/route", response_model=TestRouteResponse)
def test_route(body: TestRouteRequest, request: Request, session: Session = Depends(get_session)) -> TestRouteResponse:
    """Builds the DB-backed family into a real AgentSpec tree and runs the
    utterance through the *actual* orchestrator. By default with
    FakeProvider — the same zero-API-key path `voice-orchestrator chat`/
    `route` use, enough to check routing/tools. With
    `use_configured_provider` (D3), with the configured provider instead, so
    the reply is the one a real call would get; a provider error (bad key,
    network) comes back as a 502 with its message, not a bare 500."""
    root = repository.build_tree(session)
    if root is None:
        raise HTTPException(400, "No agents yet — create a root agent first")

    start = root.find(body.start_agent_id) if body.start_agent_id else root
    if start is None:
        raise HTTPException(404, f"No agent with id={body.start_agent_id!r}")

    call_session = CallSession(call_id=f"webapi-test-{uuid.uuid4().hex[:8]}", channel=body.channel, slots=dict(body.slots))
    call_session.agent_path = [a.id for a in _path_to(root, start.id)]

    started_at = datetime.now(timezone.utc)
    # Visitors get the try-it box too, but never on the paid provider.
    use_real = body.use_configured_provider and auth.is_owner(request)
    provider = get_provider() if use_real else FakeProvider()
    try:
        result = handle_turn(call_session, root, body.utterance, provider)
    except Exception as exc:
        if isinstance(provider, FakeProvider):
            raise
        raise HTTPException(502, f"{type(provider).__name__}: {exc}") from exc
    # Tagged "route_test" (not "chat"/"voice") so the dashboard can tell a
    # single-turn routing check apart from an actual conversation — same
    # record shape, just a different source label.
    call_log.append(call_log.from_session(call_session, source="route_test", started_at=started_at))
    return TestRouteResponse(
        agent_id=result.agent.id,
        agent_name=result.agent.name,
        resolved_by=result.routing.resolved_by,
        eligible_agents=result.routing.eligible_agents,
        handed_off=result.handed_off,
        reply=result.reply,
        tool_ids_used=result.tool_ids_used,
        provider=type(get_provider_for_agent(result.agent, default=provider)).__name__,
    )


class ConversationStart(BaseModel):
    start_agent_id: str | None = None
    channel: str = "voice"
    slots: dict = {}
    use_configured_provider: bool = False


class ConversationTurn(BaseModel):
    utterance: str
    # Merged into the session before the turn, e.g. the caller gets
    # verified mid-conversation ({"authenticated": true}).
    slots: dict = {}


@app.post("/api/test/conversations", status_code=201)
def start_conversation(body: ConversationStart, request: Request, session: Session = Depends(get_session)) -> dict:
    """Fase B: a multi-turn text test (test_conversations.py). Returns the
    conversation id and, when the starting agent has a first message, the
    same greeting event a call publishes. Visitors may use it, always on
    FakeProvider, like the single-turn box."""
    root = repository.build_tree(session)
    if root is None:
        raise HTTPException(400, "No agents yet — create a root agent first")
    start = root.find(body.start_agent_id) if body.start_agent_id else root
    if start is None:
        raise HTTPException(404, f"No agent with id={body.start_agent_id!r}")
    use_real = body.use_configured_provider and auth.is_owner(request)
    provider = get_provider() if use_real else FakeProvider()
    try:
        cid = test_conversations.start([a.id for a in _path_to(root, start.id)], body.channel, body.slots, provider)
    except test_conversations.ConversationFull as exc:
        raise HTTPException(429, str(exc)) from exc
    greeting = call_events.greeting_event(start, start.first_message) if start.first_message else None
    return {"id": cid, "greeting": greeting, "simulated": isinstance(provider, FakeProvider), "provider": type(provider).__name__}


@app.post("/api/test/conversations/{cid}/turns")
def conversation_turn(cid: str, body: ConversationTurn, session: Session = Depends(get_session)) -> dict:
    if not body.utterance.strip():
        raise HTTPException(400, "Say something first")
    root = repository.build_tree(session)
    if root is None:
        raise HTTPException(400, "No agents yet — create a root agent first")
    try:
        return test_conversations.turn(cid, root, body.utterance.strip(), body.slots)
    except test_conversations.ConversationGone as exc:
        raise HTTPException(404, "This test conversation has ended or expired. Start a new one.") from exc
    except test_conversations.ConversationFull as exc:
        raise HTTPException(429, str(exc)) from exc
    except Exception as exc:  # a real provider failing (bad key, network)
        raise HTTPException(502, f"{type(exc).__name__}: {exc}") from exc


@app.delete("/api/test/conversations/{cid}", status_code=204)
def end_conversation(cid: str) -> Response:
    test_conversations.end(cid)
    return Response(status_code=204)


@app.get("/api/calls")
def list_calls(limit: int = 200, source: str | None = None, session: Session = Depends(get_session)) -> dict:
    """Newest first, straight off `call_log.jsonl`. `source` filters to one of
    "chat"/"voice"/"route_test"; omit it for everything. Each row carries its
    analysis verdict (`call_successful`, null if never analyzed) but not its
    transcript — that's what `GET /api/calls/{call_id}` is for."""
    records = call_log.read_all()
    if source:
        records = [r for r in records if r.source == source]
    records = list(reversed(records))[: max(limit, 0)]
    verdicts = analysis_repository.verdicts_by_call(session)
    return {"calls": [{**r.summary_dict(), "call_successful": verdicts.get(r.call_id)} for r in records]}


@app.get("/api/calls/stats")
def call_stats(days: int = 14, include_test: bool = True, session: Session = Depends(get_session)) -> dict:
    """Aggregates the whole call log into what the dashboard's stat tiles
    and charts need — one pass over the (small, portfolio-scale) list, no
    separate rollup table to keep in sync. `include_test=false` drops
    `source=="route_test"` entries (the agent builder's own "try it" box)
    from every number here, for a view of real calls only."""
    records = call_log.read_all()
    if not include_test:
        records = [r for r in records if r.source != "route_test"]

    total_calls = len(records)
    total_seconds = sum(r.duration_seconds for r in records)
    avg_duration = (total_seconds / total_calls) if total_calls else 0.0
    calls_with_handoff = sum(1 for r in records if r.handoffs > 0)
    handoff_rate = (calls_with_handoff / total_calls) if total_calls else 0.0

    resolved_by_totals: dict[str, int] = {"gate_only": 0, "pattern": 0, "llm_fallback": 0}
    tool_totals: dict[str, int] = {}
    calls_by_source: dict[str, int] = {}
    for r in records:
        for level, count in r.resolved_by_counts.items():
            resolved_by_totals[level] = resolved_by_totals.get(level, 0) + count
        for tool_id, count in r.tool_counts.items():
            tool_totals[tool_id] = tool_totals.get(tool_id, 0) + count
        calls_by_source[r.source] = calls_by_source.get(r.source, 0) + 1

    # Zero-filled for the last `days` days so the chart doesn't just stop at
    # the last day with a call and look broken.
    today = datetime.now(timezone.utc).date()
    buckets = {(today - timedelta(days=i)).isoformat(): 0 for i in range(days - 1, -1, -1)}
    for r in records:
        day = datetime.fromisoformat(r.started_at).date().isoformat()
        if day in buckets:
            buckets[day] += 1
    calls_by_day = [{"date": d, "count": c} for d, c in buckets.items()]

    # Only over calls that have actually been analyzed — an unanalyzed call
    # isn't a failure, it's just not judged yet.
    verdicts = analysis_repository.verdicts_by_call(session)
    outcomes = {"success": 0, "failure": 0, "unknown": 0}
    for r in records:
        verdict = verdicts.get(r.call_id)
        if verdict is not None:
            outcomes[verdict] = outcomes.get(verdict, 0) + 1
    analyzed = sum(outcomes.values())

    return {
        "total_calls": total_calls,
        "total_minutes": round(total_seconds / 60.0, 2),
        "avg_duration_seconds": round(avg_duration, 1),
        "handoff_rate": round(handoff_rate, 3),
        "resolved_by_totals": resolved_by_totals,
        "tool_totals": tool_totals,
        "calls_by_source": calls_by_source,
        "calls_by_day": calls_by_day,
        "analyzed_calls": analyzed,
        "analysis_outcomes": outcomes,
        "success_rate": round(outcomes["success"] / analyzed, 3) if analyzed else None,
    }


@app.get("/api/calls/{call_id}")
def get_call(call_id: str, session: Session = Depends(get_session)) -> dict:
    """One call with its full transcript (routing/tools per turn) and its
    latest analysis, if any."""
    record = call_log.find(call_id)
    if record is None:
        raise HTTPException(404, f"No call with id={call_id!r}")
    row = analysis_repository.get_analysis(session, call_id)
    return {**record.as_dict(), "analysis": analysis_repository.analysis_out(row) if row else None}


@app.post("/api/calls/{call_id}/analyze")
def analyze_call(call_id: str, session: Session = Depends(get_session)) -> dict:
    """Judges the call against the current criteria and stores the result,
    replacing any earlier analysis of it. Uses the configured provider
    (VOICE_ORCH_PROVIDER): a real LLM if one is set up, otherwise
    analysis.py's labelled heuristic."""
    record = call_log.find(call_id)
    if record is None:
        raise HTTPException(404, f"No call with id={call_id!r}")
    criteria, items = analysis_repository.get_config(session)
    result = analysis.analyze(record.turns, criteria, items, get_provider())
    row = analysis_repository.save_analysis(session, call_id, result)
    return analysis_repository.analysis_out(row)


@app.get("/api/analysis/config", response_model=AnalysisConfigSchema)
def get_analysis_config(session: Session = Depends(get_session)) -> AnalysisConfigSchema:
    criteria, items = analysis_repository.get_config(session)
    return AnalysisConfigSchema(
        criteria=[
            CriterionSchema(id=c.id, name=c.name, prompt=c.prompt, kind=c.kind, expected=c.expected) for c in criteria
        ],
        data_items=[DataItemSchema(id=d.id, type=d.type, description=d.description) for d in items],
    )


@app.put("/api/analysis/config", response_model=AnalysisConfigSchema)
def put_analysis_config(body: AnalysisConfigSchema, session: Session = Depends(get_session)) -> AnalysisConfigSchema:
    try:
        analysis_repository.replace_config(
            session,
            [
                analysis.EvaluationCriterion(
                    id=c.id.strip(),
                    name=c.name.strip() or c.id.strip(),
                    prompt=c.prompt,
                    kind=c.kind,
                    expected=c.expected,
                )
                for c in body.criteria
            ],
            [analysis.DataCollectionItem(id=d.id.strip(), type=d.type, description=d.description) for d in body.data_items],
        )
    except analysis_repository.InvalidAnalysisConfig as exc:
        raise HTTPException(400, str(exc))
    return get_analysis_config(session)


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


# ---- blocco 6: the built frontend ----
# Registered last, so every /api route above wins. Resolved per request
# (not mounted at import) so the dist folder can appear after startup and
# tests can point config.WEB_DIST_DIR elsewhere.


@app.get("/{path:path}", include_in_schema=False)
def frontend(path: str):
    if path == "api" or path.startswith("api/"):
        raise HTTPException(404, "Not Found")
    dist = config.WEB_DIST_DIR.resolve()
    index = dist / "index.html"
    if not index.is_file():
        raise HTTPException(404, "Frontend not built (cd web && npm run build)")
    if path:
        candidate = (dist / path).resolve()
        if candidate.is_file() and dist in candidate.parents:
            # Vite puts content hashes in asset file names, so they can be
            # cached for good; index.html must always be revalidated.
            cache = "public, max-age=31536000, immutable" if path.startswith("assets/") else "no-cache"
            return FileResponse(candidate, headers={"Cache-Control": cache})
    # Anything else is a client-side view: hand back the app shell.
    return FileResponse(index, headers={"Cache-Control": "no-cache"})

