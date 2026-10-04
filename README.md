# Voice Orchestrator

A configurable **family of voice agents** — a router plus nested specialists — built around one
idea: *most routing decisions should never touch an LLM*. It's the text-only core of a voice-agent
architecture (telephony/STT/TTS attach on top, see "What's deliberately not here" below), designed
so the agent family, the routing logic, and the memory a call carries are all things you can
reason about, test, and measure independently.

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

Three tools ship as examples of the three kinds of thing an agent typically needs:

- **`transfer_to_human`** — keyword-triggered (`operatore`, `persona vera`, …), flips a session
  slot. The "escalate out of the whole system" case.
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

This is the **"core testuale prima"** phase, by design: the router, the agent family, the memory
scoping, the tool framework (including conditions and MCP), and structured events are all
provider-agnostic and testable without a single API key or phone call. Still explicitly deferred:
real audio — the `audio/` interfaces are scaffolded but nothing processes an actual audio frame
yet — and real telephony, including Rapida's `CallContext` pending→claimed state machine (see
above). LiveKit for transport, Deepgram for STT, ElevenLabs for TTS is the next layer, meant to
sit on top of `handle_turn()` without changing anything in this core: the architecture doc has the
reasoning for why those three specifically.

## License

MIT. See [LICENSE](./LICENSE).
