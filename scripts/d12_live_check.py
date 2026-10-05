"""D12 live check: the scripted call from voice/harness.py, with real
ElevenLabs voices instead of FakeTTS. No LiveKit server, microphone or
Deepgram involved (input is text, audio is captured in memory), so it runs
anywhere with outbound HTTPS and an ELEVENLABS_API_KEY.

    ELEVENLABS_API_KEY=... python scripts/d12_live_check.py [out_dir]

Checks, and exits non-zero if any fails:
  1. every turn gets a spoken reply (real audio frames from ElevenLabs);
  2. the router answers with the session's default voice, and after the
     handoff the billing agent answers with *its* voice_id;
  3. after "arrivederci" (end_call) the call ends only once the farewell
     has finished playing.
Writes one WAV per reply into out_dir (default: d12_out/) so the voice
change can be heard, not just read in a log.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from voice_orchestrator.agents.registry import AgentSpec, ToolBinding
from voice_orchestrator import config
from voice_orchestrator.voice.agent import elevenlabs_tts
from voice_orchestrator.voice.harness import run_scripted_call

# Two of the preset voices the agent builder's VoicePicker offers.
BILLING_VOICE = "VR6AewLTigWG4xSOukaG"  # Arnold
SALES_VOICE = "EXAVITQu4vr4xnSDxMaL"  # Bella


def family() -> AgentSpec:
    billing = AgentSpec(
        id="billing", name="Fatturazione", description="bollette e pagamenti", triggers=["bolletta"],
        voice_id=BILLING_VOICE, tools=[ToolBinding(id="end_call")],
    )
    sales = AgentSpec(id="sales", name="Vendite", description="offerte", triggers=["offerta"], voice_id=SALES_VOICE)
    return AgentSpec(id="router", name="Centralino", description="smista le chiamate", children=[billing, sales])


async def main(out_dir: Path) -> int:
    if not config.ELEVENLABS_API_KEY:
        print("ELEVENLABS_API_KEY non impostata")
        return 2
    call = await run_scripted_call(
        family(),
        ["buongiorno", "ho un problema con la bolletta", "arrivederci"],
        default_tts=elevenlabs_tts(),  # exactly what worker.py builds
        # Not the agent's own builder: the harness wraps this to log voices.
        voice_factory=lambda spec: elevenlabs_tts(voice_id=spec.voice_id),
        default_voice_label="default",
    )

    voices = [s.voice for s in call.syntheses]
    segs = call.output.segments
    print("Turni:")
    for (agent_id, text), seg, voice in zip(call.replies, segs, voices):
        print(f"  {agent_id:8s} voce={voice:22s} audio={seg.duration:5.2f}s  {text[:60]!r}")
    if call.agent.ended_at is not None and segs:
        print(f"Chiusura: {call.agent.ended_at - segs[-1].finished_at:+.2f}s rispetto alla fine dell'ultimo audio")

    checks = {
        "3 risposte, tutte con audio": len(segs) == 3 and all(s.duration > 0.3 for s in segs),
        "agenti: router, billing, billing": [a for a, _ in call.replies] == ["router", "billing", "billing"],
        "voci: default, poi quella di billing": voices == ["default", BILLING_VOICE, BILLING_VOICE],
        "riattacca dopo la fine del saluto": (
            call.agent.ended_at is not None and bool(segs) and segs[-1].finished_at is not None
            and call.agent.ended_at >= segs[-1].finished_at
        ),
    }
    for name, ok in checks.items():
        print(f"[{'OK' if ok else 'FALLITO'}] {name}")
    paths = call.output.write_wavs(out_dir, [f"{a}_{v}" for (a, _), v in zip(call.replies, voices)])
    print("WAV:", ", ".join(str(p) for p in paths))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("d12_out"))))
