"""Regenerate web/src/exampleCall.json: the example call the call page shows
before you start one (blocco 7, fase C).

It is not hand-written. The script runs a scripted caller through the real
router on config/agents.yaml, with the same FakeProvider the public demo
uses, and records the exact events a live call publishes on the data
channel (call_events.py). Latencies are dropped because they describe this
machine, not the call. Re-run after changing the family:

    python scripts/make_example_call.py
"""
from __future__ import annotations

import json
from pathlib import Path

from voice_orchestrator import call_events
from voice_orchestrator.agents.registry import load_family
from voice_orchestrator.config import AGENTS_FILE
from voice_orchestrator.llm import FakeProvider
from voice_orchestrator.orchestrator import handle_turn
from voice_orchestrator.state import CallSession

CALLER = [
    "Ho un problema con la bolletta",
    "Quanto costa il roaming in Francia?",
    "Perfetto, grazie. Arrivederci",
]

OUT = Path(__file__).resolve().parents[1] / "web" / "src" / "exampleCall.json"


def main() -> None:
    root = load_family(AGENTS_FILE)
    session = CallSession(call_id="example", channel="voice")
    provider = FakeProvider()
    events = [call_events.greeting_event(root, root.first_message)]
    for seq, utterance in enumerate(CALLER, start=1):
        from_id = session.current_agent_id or root.id
        result = handle_turn(session, root, utterance, provider)
        event = call_events.turn_event(root, from_id, utterance, result, session, seq, simulated=True)
        event["latency_ms"] = None
        events.append(event)
        if "end_call" in result.tool_ids_used:
            events.append(call_events.ended_event("end_call"))
            break
    OUT.write_text(json.dumps(events, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(events)} events to {OUT}")


if __name__ == "__main__":
    main()
