# Voice Orchestrator

A configurable **family of voice agents** — a router plus nested specialists — built around one
idea: *most routing decisions should never touch an LLM*. The router, agent family, memory
scoping, and tool framework are a provider-agnostic text core (`chat`/`route`/`eval` all run
against it with zero API keys); a real-time voice layer (LiveKit Agents + Deepgram + ElevenLabs,
see "Voice layer" below) sits on top of that exact same core, unchanged, so the agent family, the
routing logic, and the memory a call carries are all things you can reason about, test, and
measure independently of whether the call is typed or spoken.

Demoed on a fictional telecom customer line, **Meridian Telecom**: a receptionist that routes
callers to Billing, Sales, or Technical Support — the latter itself split into Internet and
TV/decoder specialists, to show that sub-agents nest to any depth.

This project is the implementation of the architecture decisions discussed in
[`voice-orchestrator-architecture.md`](./voice-orchestrator-architecture.md) (the research doc
comparing Twilio/Telnyx/LiveKit, Deepgram/Soniox + ElevenLabs, GPT vs. Gemini, and the
ElevenLabs/Parloa/Wonderful/Calpurnia routing patterns). Read that first if you want the "why
these choices" story; this README is the "how it's built" story.

## The core idea: a two-level router, LLM as last resort

The architecture research's central finding was that the fastest, most reliable voice agent
systems (Parloa's deterministic gates, Calpurnia-style lightweight routers) treat the
conversational LLM as the *expensive, slow, last-resort* way to decide who should handle an
utterance — not the default way. This project implements that directly as three levels, tried in
order, each only reached if the previous one couldn't decide:

1. **Gate (`routing/gate.py`)** — a deterministic boolean check on session state (e.g.
   `authenticated == true`) that decides which agents are even *candidates*. Costs
   microseconds. If it leaves exactly one eligible candidate, routing is already done — no
   model involved at all. This is also the one real **security boundary** in the system: it's
   evaluated with a hand-rolled `ast`-based safe expression walker, never Python `eval()`,
   because a config file (which someone other than the code's author might edit) handed to
   `eval()` would stop being a boundary. `test_gate_expression_rejects_unsafe_input` proves an
   injection attempt (`__import__('os').system(...)`) raises `UnsafeExpression` instead of running.

2. **Classifier (`routing/classifier.py`)** — a lightweight keyword/stem scorer over the agents
   the gate left eligible. No model call; just regex counting with a margin requirement (the
   winner must beat the runner-up, or it's ambiguous). This is the Calpurnia-style "router with a
   lighter model" idea, pushed even further — here it isn't a model at all.

3. **LLM fallback (`llm.py`'s `classify()`)** — only reached when steps 1–2 couldn't decide.
   Can also return `STAY`, meaning "none of the candidates genuinely fit — keep the current
   agent." Without a `STAY` option, a router is forced to transfer on every ambiguous utterance
   (including plain greetings), which causes exactly the agent-ping-ponging the architecture
   research flagged as a real failure mode.

**Known limitation, by design:** routing only ever looks downward at the current agent's children,
never back up to the root or sideways to a sibling — a leaf agent (no children, e.g. `roaming`)
can only be left via a tool it was explicitly given (`transfer_to_human`), not by asking it an
unrelated question. Fine for a strict IVR-style tree; a caller freely wandering topics would need
an explicit "return to root" transition this sample family doesn't build (see `routing/router.py`'s
docstring for the detail).

Every routing decision records which level resolved it (`RoutingEvent.resolved_by`), which is
what turns "we optimized for latency" into a number you can check:

```
$ voice-orchestrator eval
...
Hit-rate: 8/8
Resolved by level: {'gate_only': 1, 'pattern': 6, 'llm_fallback': 1}
```

75% of this eval set resolves without ever calling an LLM. `test_most_decisions_avoid_the_llm_fallback`
asserts this stays ≥60% as the eval set grows.

## The agent family is data, not code

`config/agents.yaml` **is** the family — a tree of agents, each possibly with `children` (nested
sub-agents, to any depth). This was an explicit requirement: being able to add, remove, or
re-nest an agent without touching code.

```
$ voice-orchestrator agents list
router — Receptionist
├── billing — Billing Agent  (eligibility: authenticated == true)
├── sales — Sales & Upgrades Agent
├── roaming — Roaming & International Agent
└── tech_support — Technical Support
    ├── tech_internet — Internet Connectivity Support
    └── tech_tv — TV & Set-Top-Box Support

$ voice-orchestrator agents add --id vip_support --parent sales \
    --name "VIP Escalations" --description "Handles VIP customer escalations" \
    --triggers vip,escalation --tools transfer_to_human
Added 'vip_support' under 'sales'.
```

`agents/registry.py`'s `AgentSpec` is the typed shape behind the YAML (`id`, `name`,
`description`, `system_prompt`, `eligibility`, `triggers`, `tools`, `knowledge`, `voice`,
`children`); `load_family`/`save_family` round-trip it, and `add_agent`/`remove_agent` are the
functions the CLI calls (also usable directly, e.g. from a future admin UI).

## Memory: nobody sees the raw, ever-growing transcript

The second half of the research question ("how much should the router vs. each agent
remember?") is answered in `memory.py`, following the hierarchical split the research surfaced
(critical info persists, working info is temporary, historical info gets compressed):

- **`RouterView`** — what the router sees to make a routing decision: a rolling summary, the
  last 2 turns, and the extracted slots. Never the full transcript.
- **`HandoffPackage`** — what a specialist receives when handed a call: *not* "everything the
  router saw," but the same structured shape (summary + recent turns + slots) plus *why* it was
  handed off.
- **`maybe_condense()`** — once the transcript passes 6 turns, folds everything except the last 2
  into `rolling_summary` via the LLM provider's `summarize()`. This is explicitly documented
  (see `orchestrator.py`) as conceptually off the latency-critical path: in a real streaming
  system it would run in the background right after the reply starts playing, not block the next
  turn. The CLI demo runs it inline since there's no real audio I/O to overlap it with yet.

`state.py`'s `CallSession` keeps **two** turn lists on purpose: `turns` is the active, condensable
window; `full_log` is never truncated, so exporting a call for review or debugging doesn't lose
anything the condensing step folded away.

No Redis. A call is one process; `CallSession` is a plain Python object. The research called out
Redis as the right answer only once the agent family runs as *separate* processes needing
cross-process pub/sub (e.g. a transfer that hands off to a different worker) — not for a
single-process call loop like this one.

## Tools: provider-agnostic on purpose

`tools/base.py`'s `Tool` ABC has two methods: `should_trigger(agent, utterance, session)` and
`run(agent, utterance, session)`. This is deliberately **not** native provider function-calling
(OpenAI tools / Anthropic tool_use / Gemini function calling) — those differ per provider and
don't exist at all in the zero-API-key `FakeProvider` mode this whole project defaults to. Once
you commit to one real provider, swapping this for native tool_use is a contained change (one
file); until then, every provider runs the same tool loop.

Four tools ship as examples of the kinds of thing an agent typically needs:

- **`transfer_to_human`** — keyword-triggered (`operatore`, `persona vera`, …), flips a session
  slot. The "escalate out of the whole system" case.
- **`end_call`** — keyword-triggered (`basta così`, `arrivederci`, …), the built-in-tool
  equivalent of ElevenLabs' own `end_call`. Sets `session.slots["call_ended"]`; the voice layer
  (`voice/agent.py`) is what actually hangs up, a short while after speaking the goodbye.
- **`check_account_status`** — keyword-triggered mock of an external API call
  (`account_tool.py`'s `_fetch_account()` is the one function you'd point at a real billing
  system). The "call out to a backend" case.
- **`knowledge_lookup`** — *always* triggered when an agent has `knowledge` configured (it's
  grounding for every reply, not a discrete action). BM25-only retrieval over markdown files
  split on `##` headers — deliberately a lighter stack than the
  [Company Brain](../company-brain) project's hybrid dense+BM25+graph+rerank pipeline. The point
  here is the *integration pattern* ("an agent can ground replies in its own knowledge base"),
  not a second copy of that pipeline. If a knowledge base ever gets big or ambiguous enough to
  need dense retrieval and reranking, swap this tool's internals for Company Brain's
  `retrieval.py` — same `Tool` interface, different engine underneath.

## Four pieces adapted from a real production platform

While building this, I read through [Rapida](https://github.com/rapidaai/voice-ai) — an
open-source, ~175k-line Go voice-AI platform — to sanity-check this project's architecture against
something running in production. The verdict: **the two-level router is not something Rapida (or,
as far as I could find, anyone at that scale) does** — their agent graph calls the LLM, with
native tool-calling, on every single turn to decide the next node. So the core thesis here stands.
But Rapida's *infrastructure* is, unsurprisingly, far more mature than a portfolio demo — four
pieces were worth adapting in, rewritten to fit this project's style rather than copied:

**Tool conditions.** Rapida scopes a tool to a channel/mode via a bespoke string-switch matcher.
Here, a tool's `condition` (in `agents.yaml`) is evaluated by the *same* AST-safe gate that already
guards agent eligibility (`routing/gate.py`) — one mechanism, and more expressive (it combines
conditions with `and`/`or` instead of checking one field at a time). `CallSession.channel` and
`gate_context()` (`state.py`) are the plumbing underneath. Billing's `check_account_status` is
gated `channel == 'voice'` — a balance figure shouldn't land in a text thread. Toggle it live in
`chat` with `/channel sms`.

**MCP tool support.** `tools/mcp_tool.py`'s `MCPTool` points an agent at any
[MCP](https://modelcontextprotocol.io) server and auto-discovers every tool it exposes — matched
against the utterance to a remote tool, you can run with zero setup. `tools/demo_mcp_server.py`
bundles one (`get_roaming_rate`, `check_service_outage`, fake data) so the feature is exercisable
without any external account; `config/mcp_servers.yaml` wires it to the new `roaming` agent. Kept
honest about where it's a simplification: `should_trigger`/`run` stay synchronous like every other
`Tool`, so each call reconnects rather than holding a session open, and the argument passed to the
remote tool is a best-effort guess (the whole utterance into the tool's first parameter) rather
than an LLM extracting it properly — Rapida solves both by making every tool call go through
native function-calling. That's a real trade-off this project makes deliberately (see the tools
section above), not an oversight.

**Structured observability events.** Rapida's agent graph emits a typed event
(`AgentTransitionMatched`/`Triggered`/`MissingEdge`) at every step. `observability.py`'s `Event` +
`CallSession.event_log`/`event_counts()` is the same idea, generalized to cover routing decisions,
handoffs, and tool calls — alongside, not instead of, the existing `routing_log` the eval depends
on. `chat` prints a summary at the end of each call; wiring a real sink (OpenTelemetry, a metrics
backend) later is a matter of iterating `event_log`, not changing how events get recorded.

**Audio-layer interfaces.** Rapida keeps VAD, end-of-speech, and noise reduction as three separate
pluggable providers (`silero_vad`/`ten_vad`, `silence_based_eos`/`livekit_eos`, a denoiser) rather
than one blob of "audio processing" — a production system validating a split this project had only
guessed at. `audio/` scaffolds the same three as ABCs (`VADProvider`, `EndOfSpeechProvider`,
`DenoiserProvider`) with simple reference implementations (`NoOpVAD`, `SilenceBasedEOS`,
`PassthroughDenoiser`) — not real audio processing (there's no audio yet), just the documented
attachment point for when the real voice layer lands.

One piece deliberately **stayed a note, not code**: Rapida's `CallContext` is a Postgres-backed
pending→claimed state machine that bridges a telephony webhook (call setup) arriving on one path
with the media WebSocket/SIP connection arriving on another — a real race condition in production
telephony. A synchronous CLI demo has no such race to solve, so building it now would be solving a
problem this project doesn't have yet. It's a confirmed, concrete item for when real Twilio/Telnyx
webhooks get wired in, not before.

## Voice layer: LiveKit Agents + Deepgram + ElevenLabs

Everything above is the text core — a call is a Python string in, a Python string out, no audio
anywhere. `src/voice_orchestrator/voice/` is the real-time layer that sits on top of it, so a
caller can actually talk instead of typing into `chat`. It changes nothing in `orchestrator.py`,
`routing/`, `tools/`, or `memory.py` — those are the exact same modules a voice call and a
`chat` REPL session both run through.

**Why LiveKit Agents, specifically.** The architecture doc compared Twilio/Telnyx/LiveKit for
transport and picked LiveKit for the reasons laid out there (WebRTC-native, open-source worker
model, a hosted Cloud tier for testing without touching telephony). What made it the right fit
*here* too: LiveKit's `Agent` class has one override point, `llm_node()`, that receives the
conversation so far and is expected to yield reply text — nothing else about the pipeline (audio
capture, VAD, STT framing, TTS playback, interruption handling) is this project's problem anymore.
That's the same shape this project already had: `handle_turn()` takes a string, returns a string.
`llm_node` is just a new place to call it from.

**How it's wired** (three files, each doing one job):

- **`voice/bridge.py`** — no `livekit-agents` import, tested with zero extra dependencies.
  `VoiceBridge` holds one `CallSession` + the agent family + an `LLMProvider`, same as a `chat`
  session; `.turn(utterance)` is a one-line call into the existing `handle_turn()`.
- **`voice/agent.py`** — `OrchestratorAgent(Agent)` overrides `llm_node()`: pulls the latest
  caller message out of LiveKit's `ChatContext`, calls `bridge.turn()`, yields the reply string.
  It deliberately never delegates to `Agent.default.llm_node()` — there's no real chat model
  backing this agent at all, because the router+tools+memory stack *is* the decision-making step,
  the same thesis the rest of this README argues. The one wrinkle: `handle_turn()` is synchronous
  and can itself call `asyncio.run()` (`MCPTool.run()` does, to reach the demo MCP server), which
  would crash if awaited directly inside `llm_node` — already running inside LiveKit's own event
  loop. `asyncio.to_thread()` runs it on a worker thread instead, sidestepping the "cannot be
  called from a running event loop" error.
- **`voice/worker.py`** — the LiveKit worker entrypoint: wires `deepgram.STT(model="nova-3",
  language="multi")`, `elevenlabs.TTS(model="eleven_flash_v2_5")` (Flash v2.5, not the plugin's
  default `eleven_turbo_v2_5` — picked for the sub-300ms round-trip budget the architecture doc
  set), and `silero.VAD.load()`, then starts an `AgentSession` around one `OrchestratorAgent`. The
  `__main__` block sets `WorkerOptions(num_idle_processes=0)` — confirmed directly against the
  installed `livekit-agents`, outside dev mode this defaults to **2**, prewarming two full OS
  subprocesses (interpreter + the Silero VAD model + the Deepgram/ElevenLabs SDKs) before any call
  ever arrives, which is real memory spent at idle for zero benefit on a single-worker demo. **This
  is harm reduction, not a fix for an underpowered host**: LiveKit's own deployment docs size a
  voice-AI worker at 4 cores/8GB as a baseline, and `job_memory_warn_mb` defaults to 1000 (LiveKit's
  own assumption that a *single* job can reasonably use 1GB) — both well above a 512MB instance.
  If you deploy this to Render's $7/mo Starter plan (512MB) as the README's earlier Render section
  describes, expect OOM kills (Render's own error: "Ran out of memory (used over 512MB)") under
  real load regardless of this setting; the Standard plan (1 CPU/2GB, $25/mo) is the first tier
  that matches what LiveKit itself assumes, not a generous margin above it.
- **`voice/usage_guard.py`** — a self-imposed daily cap on call minutes, because none of LiveKit
  Cloud, Deepgram, or ElevenLabs offer a hard spending cap of their own (and if this ever runs on
  a host instead of a laptop, neither does Render — their support confirmed overage just gets
  billed with an email warning, no cap). `UsageGuard` tracks total call minutes per UTC calendar
  day in a small JSON file (`data/usage_log.json` by default); `worker.py`'s `request_fnc` rejects
  a *new* call outright once the day's budget (`VOICE_ORCH_MAX_CALL_MINUTES_PER_DAY`, default 60)
  is used up — rejecting costs nothing (no room, no STT/TTS connection opened), unlike accepting
  and immediately hanging up. A call already in progress when the cap is hit is left to finish.
  Minutes, not a per-provider euro estimate, is the metric on purpose: a euro figure needs
  Deepgram/ElevenLabs/Anthropic's current per-unit prices hardcoded somewhere, which drift and go
  stale silently; minutes needs no pricing assumptions at all. `tests/test_usage_guard.py` covers
  the day-rollover and corrupt-file-is-zero-not-a-crash cases with no LiveKit import.

`tests/test_voice_bridge.py` covers the STT-transcript→reply path (including the "blank/noise
transcript → no reply" case) against `FakeProvider`, with no LiveKit connection, no microphone,
and no API key — install nothing beyond `pip install -e ".[dev]"` to run it. The three LiveKit
plugins are only needed to actually *run* a call.

**Running it for real.**

```
pip install -e ".[voice]"
cp .env.example .env   # fill in the five keys below, then `export $(cat .env | xargs)` or similar
python -m voice_orchestrator.voice.worker dev
```

Four free accounts, no telephony or custom web client needed to try it:

- **[LiveKit Cloud](https://cloud.livekit.io)** — the free Build plan gives 1,000 agent-session
  minutes/month and 5,000 WebRTC minutes, no credit card required. Create a project, copy
  `LIVEKIT_URL`/`LIVEKIT_API_KEY`/`LIVEKIT_API_SECRET` from its Settings page.
- **[Deepgram](https://console.deepgram.com/signup)** — $200 in free credit on signup, no card
  required; copy the API key into `DEEPGRAM_API_KEY`.
- **[ElevenLabs](https://elevenlabs.io)** — the free plan includes a monthly character allowance
  and API access; grab `ELEVENLABS_API_KEY` from account settings (check elevenlabs.io/pricing for
  the current limits — they change the free tier's numbers more often than the other two).

With those five env vars set, `python -m voice_orchestrator.voice.worker dev` connects to LiveKit's
hosted **Agents Playground** (a link printed in the terminal) — open it in a browser, grant mic
access, and talk to Meridian Telecom's receptionist live, no phone number or SIP trunk needed for
a first test. `start` instead of `dev` is the long-lived-worker mode for when real rooms/SIP
trunking get wired in later.

## Agent builder: a web UI on the same core

Everything above — the router, the agent family, memory, tools, the voice layer — is reachable
only through `agents.yaml` and the CLI. `src/voice_orchestrator/webapi/` (FastAPI) and `web/`
(React + Vite + TypeScript) add a second way in: a browser UI to create, edit, and delete agents
in the family tree, and a "try it" box that runs a real utterance through the actual router —
without hand-editing YAML or restarting anything. This is the product-layer gap between a CLI demo
and something that resembles an ElevenLabs Agents / Vapi dashboard; the routing engine underneath
is unchanged.

**Dual source of truth, on purpose — with an explicit bridge.** `config/agents.yaml` stays
exactly what it was — the CLI's and test suite's source of truth, never touched automatically by
the web layer. The web UI reads and writes a separate SQLite database (`data/agents.db`,
gitignored — it's a developer's own edited family, not something to commit), seeded once from
`agents.yaml` the first time it's empty (`webapi/seed.py`'s `seed_if_empty()` — idempotent, safe
to call on every startup, so a server restart never wipes edits made through the UI). The two
aren't unified by default: doing that automatically would mean changing already-tested CLI code to
serve a newer, less-tested UI layer, and would mean every save in the browser silently overwrites a
file tracked in git. What exists instead is a one-click, explicit export: the "↓ Esporta verso
agents.yaml" button in the builder's sidebar calls `POST /api/agents/export`, which writes the
current DB-backed family back to `config/agents.yaml` with the exact same `save_family()` the
CLI's own `agents add`/`agents remove` commands already used (so this isn't a new serializer, just
a new caller of one that shipped since the first commit). Nothing needs restarting afterwards —
`chat`/`route`/`eval` and the voice worker's `new_voice_bridge()` all call `load_family()` fresh,
so the very next invocation already sees the export, even against an already-running voice worker
process. It's a manual action by design, not a sync: treat the two as separate environments day to
day (YAML = what ships in the repo as the demo family; SQLite = your local playground), and export
only when you actually want the browser's edits to become what `chat`, `route`, `eval`, and a real
voice call all exercise.

**What's actually stored.** `webapi/models.py`'s `AgentRow` mirrors `AgentSpec` (`agents/registry.py`)
field-for-field, with one simplification: `triggers`/`tools`/`knowledge` are stored as JSON text on
the agent's own row rather than normalized child tables, because nothing in this UI queries or
filters on them independently of their parent agent — every read and write handles them as one
unit, same as a form submit does.

**No duplicated routing logic.** `POST /api/test/route` doesn't reimplement or approximate
routing — it rebuilds the real `AgentSpec` tree from SQLite and calls the actual
`orchestrator.handle_turn()` against `FakeProvider`, the same zero-API-key path `chat`/`route`
use. The UI's "try it" box is exactly as trustworthy as the CLI's `route` command, because it's
the same code.

**Running it** (two servers, both local-dev only — the FastAPI app's CORS only allows
`localhost:5173`, and it has no auth, so don't expose it on the open internet as-is):

```
# Terminal 1 — backend (installs fastapi/uvicorn/sqlalchemy)
pip install -e ".[webapi]"
uvicorn voice_orchestrator.webapi.app:app --reload --port 8000

# Terminal 2 — frontend
cd web
npm install
npm run dev
```

Open `http://localhost:5173`. The Vite dev server proxies `/api/*` to `localhost:8000`
(`web/vite.config.ts`), so there's no CORS fiddling in dev. The "Agent builder" tab is the agent
tree (click to edit, `+` to add a child under any node) plus the edit/create form, the
text-based "try it" box (wired to `POST /api/test/route`), and the "Server MCP" panel below (see
next). `tests/test_webapi.py` (37 tests, `TestClient` against a temp SQLite file) covers the full
CRUD surface, the auto-seed-once behavior, both the happy and error paths (duplicate id, missing
parent, delete-the-root, delete-with-children), the MCP-server endpoints below, and the
voice-token endpoints below.

**"Test live (voce)" tab — a real call, not a text simulation.** `web/src/components/VoiceTestConsole.tsx`
talks to LiveKit directly with the browser's own microphone, through
[`livekit-client`](https://www.npmjs.com/package/livekit-client) — it has no idea the router,
tools, or orchestrator exist, the same separation `chat`/the CLI already has from the voice layer.
`POST /api/voice/token` (`webapi/voice_token.py`) is the only backend piece involved: it signs a
short-lived LiveKit room token locally (no network call, just `livekit-api`'s `AccessToken`) for a
freshly-named room — exactly what the hosted Agents Playground's own backend does for you. Click
"Connetti e parla", grant mic access, and whatever worker is running
(`python -m voice_orchestrator.voice.worker dev`) auto-joins the new room and answers, because a
LiveKit Agents worker auto-dispatches to any room by default — the same mechanism that already
makes the Playground work, just with this project's own UI around it instead. If `LIVEKIT_URL`/
`LIVEKIT_API_KEY`/`LIVEKIT_API_SECRET` aren't set on the backend, the tab greys itself out with that
exact explanation (`GET /api/voice/status`) rather than letting a click fail with an opaque network
error.

**"Dashboard" tab — real calls, not mock numbers.** Every call that finishes — a `chat` session, a
real voice call, or one run of the "try it" box — gets one line appended to `data/call_log.jsonl`
by `call_log.py` (`call_log.from_session()` reads straight off the `CallSession` that already
existed: `routing_stats()`, `event_log`, `handoff_log`; nothing new to track by hand).
Deliberately a plain JSONL file, not a SQLite table: `call_log.py` lives in the core, so `cli.py`
and `voice/worker.py` can both log a call with zero extra dependencies — the same "nothing else
imports webapi's deps" promise as everywhere else in this README, just pointed the other way.
`GET /api/calls/stats` and `GET /api/calls` (`webapi/app.py`) read and aggregate that file on
request — no separate rollup to keep in sync, since the log is small by construction (a portfolio
demo's worth of calls, not production volume). The dashboard itself (`web/src/components/Dashboard.tsx`,
charts via [Recharts](https://recharts.org)) shows total calls/minutes/avg duration/handoff rate,
calls-per-day, the routing-level breakdown (the same `gate_only`/`pattern`/`llm_fallback` split
`eval` reports), and tool usage — with a toggle to exclude the agent builder's own test-route calls
from the aggregates, since those aren't real conversations.

**"Server MCP" panel — dynamic tools, no restart, no hand-edited YAML.** Before this, the only way
to add an MCP tool was to hand-edit `config/mcp_servers.yaml` and restart every process — invisible
to the web UI entirely, even though the agent builder could already attach a tool id to an agent.
The panel at the bottom of the "Agent builder" tab closes that gap: list, create, edit, and delete
MCP servers from the browser, with every change usable on the very next turn. It follows the exact
same dual-source-of-truth pattern as the agent tree above it: `webapi/models.py`'s `McpServerRow`
table is seeded once from `config/mcp_servers.yaml` (`webapi/seed.py`'s `seed_mcp_if_empty()`), then
edited independently of it — the YAML file still works unchanged for the CLI/tests, nothing about
that path was touched.

The part worth being explicit about is how a server created through the browser becomes callable
without restarting the backend process. `orchestrator.handle_turn()` calls `tools.get_tool()`
against the module-level `tools.REGISTRY` dict directly, with no pluggable-registry parameter — and
adding one would mean changing that already-tested core code to serve a newer, less-tested UI
layer, the same ordering problem the agent tree's dual-source-of-truth note above already explains
for a different file. So instead, `webapi/mcp_sync.py` mutates `tools.REGISTRY` *in place* at
runtime: it's called once at startup (after seeding) and again after every create/update/delete,
and each time it adds/replaces every `"mcp:<name>"` entry from the current DB rows and removes any
`"mcp:<name>"` entry that's no longer in the table. `GET /api/tools` needs no code change at all to
see this — it already just reads `sorted(REGISTRY)`. `tests/test_webapi.py`'s
`test_mcp_server_create_makes_it_usable_without_a_restart` proves this isn't just a later `GET`
picking up a background refresh: it creates a server and calls `/api/test/route` in the same
request cycle, same process, zero restart in between.

**Security note, stated plainly rather than glossed over:** an MCP server's `command`/`args` is
whatever gets handed to the OS to spawn a real local subprocess (`tools/mcp_tool.py`). Letting a
browser client create one is, honestly, a "run an arbitrary command on this machine" capability.
That's acceptable only under the threat model this backend already documents for itself — local
dev only, CORS locked to the Vite dev server's own origin, no authentication — and the panel says
so in the UI itself, not just here. Don't expose this API past localhost without adding real auth
first.

**"Conversazioni" tab — transcripts, per-turn routing, post-call analysis.** Every logged call now
carries its full transcript (`call_log.transcript_from_session()`), and each turn says *why* it went
where it did: the caller's turn carries its routing decision (level, candidates, latency, reason, and
any handoff), the agent's reply carries the tools that grounded it. No new bookkeeping in the
orchestrator was needed for this — `route()` already records exactly one `RoutingEvent` per turn, and
handoff/tool events are bucketed into each exchange by timestamp. The tab lists calls, opens one as a
chat-style transcript with that trace under every turn, and runs post-call analysis on it — the
equivalent of ElevenLabs' `evaluation.criteria` + `data_collection`. Criteria and data fields are
edited in the same tab and apply to the whole family, not one agent: a call crosses several agents,
and it's the call that gets judged. `analysis.py` (core, standard library only) does the judging: with
a real provider configured it's one LLM call asked for strict JSON, parsed defensively (a garbage reply
is reported as a failed analysis, not silently replaced); with the zero-key `FakeProvider` it's a
word-overlap heuristic that states in every rationale exactly what it matched, and the UI labels it
"euristica, non un giudizio LLM". That heuristic exists so the pipeline runs without keys — its
verdicts are not an evaluation, and the README says so here too. Results are stored per call in
SQLite (`webapi/analysis_repository.py`) and feed a success-rate tile on the dashboard, computed only
over calls that were actually analyzed. The working roadmap and gap map against ElevenLabs live in
[`docs/ROADMAP.md`](docs/ROADMAP.md).

**Deliberately not here (yet):** phone-number provisioning and multi-tenant auth/billing. Neither
is what differentiates this project (the routing thesis and the clean core do that); they're the
genuinely-different-scale infrastructure gap between a portfolio demo and ElevenLabs Agents/Vapi
that no amount of UI polish closes.

## LLM providers: one abstraction, a free default

`llm.py`'s `LLMProvider` ABC has three methods — `classify`, `respond`, `summarize` — kept
separate so each can be reasoned about (and swapped) on its own. `FakeProvider` (zero API keys,
deterministic word-overlap/template rules) is the default every CLI command and the whole test
suite run against. `AnthropicProvider`, `OpenAIProvider`, and `GeminiProvider` — the three the
architecture research compared — are drop-in real implementations; switching is one environment
variable:

```
VOICE_ORCH_PROVIDER=anthropic   # or openai, gemini, fake (default)
ANTHROPIC_API_KEY=...           # matching key for whichever provider
```

## Setup

```
pip install -e ".[dev]"
voice-orchestrator agents list
voice-orchestrator eval
voice-orchestrator chat
```

`chat` simulates a call in the terminal. `/auth on` / `/auth off` toggle the `authenticated` slot
mid-call, to see the gate actually block/unblock Billing live; `/channel sms` switches the
channel, to see the `check_account_status` tool condition block it live:

```
$ voice-orchestrator chat
Meridian Telecom — digita 'exit' per terminare la chiamata.

Tu: quanto devo pagare questo mese?
Billing Agent: [Billing Agent] Grounding passages from Billing Agent's knowledge base: ... (pattern, handoff→billing, tools=['check_account_status', 'knowledge_lookup'])
Tu: il wifi non si connette
Internet Connectivity Support: [Internet Connectivity Support] ... (pattern, handoff→tech_internet, tools=['knowledge_lookup'])
Tu: voglio parlare con un operatore
Internet Connectivity Support: [Internet Connectivity Support] ... (gate_only, tools=['transfer_to_human'])
Tu: exit

Routing breakdown this call: {'gate_only': 1, 'pattern': 2, 'llm_fallback': 0}
Events logged this call: {'router.routing_decision': 3, 'agent.handoff': 2, 'tool.tool_triggered': 5}
```

`voice-orchestrator route "<utterance>" --start <agent_id> --set key=value --channel voice` tests
a single routing decision in isolation (handy when editing `agents.yaml` triggers). `pytest` runs
the full test suite (routing correctness over a hand-labeled eval set, the gate's security
property, full-turn handoffs + tool triggering + tool conditions, structured events, a real
stdio round-trip against the bundled MCP demo server, the audio-provider reference
implementations, and the agent add/remove roundtrip) — all against `FakeProvider` and a local
subprocess, so it needs no API keys or external network either.

## What's deliberately not here (yet)

The router, the agent family, the memory scoping, the tool framework (including conditions and
MCP), structured events, and — as of the voice layer above — a real LiveKit/Deepgram/ElevenLabs
audio pipeline are all built and tested. Still explicitly deferred:

- **Real telephony.** The voice layer talks to LiveKit's Agents Playground (browser mic) or any
  LiveKit room, but nothing here wires up a phone number via SIP/Twilio/Telnyx trunking yet. That
  also means Rapida's `CallContext` pending→claimed state machine (see above) still has no race
  to solve — it shows up the moment a telephony webhook and a media connection can arrive out of
  order, which a Playground-only call never does.
- **The `audio/` provider interfaces** (`VADProvider`, `EndOfSpeechProvider`, `DenoiserProvider`)
  are still scaffolding, not wired into the real pipeline — `worker.py` uses LiveKit's own Silero
  VAD plugin directly instead. They stay as the documented attachment point for a future
  non-LiveKit transport, or for swapping in a different VAD/denoiser than whatever LiveKit's
  plugin ecosystem offers.
- **Downward-only routing and the leaf-agent escape hatch** (see `routing/router.py`'s docstring)
  — unchanged by adding real audio; still a property of the router itself, not the transport.
- **Real multi-turn voice latency measurement.** The eval set and `RoutingEvent.latency_ms`
  measure routing/tool latency against text input; nothing yet measures the full voice round-trip
  (STT partial → router → TTS first byte) the architecture doc's sub-300ms budget was about.

## License

MIT. See [LICENSE](./LICENSE).
