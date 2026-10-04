"""The real-time voice layer: LiveKit Agents (transport + session) +
Deepgram (STT) + ElevenLabs (TTS) + Silero (VAD), sitting on top of the
text-core this package already is. Nothing in `orchestrator.py`,
`routing/`, `tools/`, or `memory.py` changes to support this — this
package only adds a way to *drive* `orchestrator.handle_turn()` from a
real phone/browser call instead of a REPL line or a scripted eval case.

Two files, two different dependency footprints:
  - `bridge.py` — pure, no `livekit-agents` import. Testable (and tested)
    with zero extra dependencies, same zero-API-key-by-default ethos as the
    rest of this project.
  - `agent.py` / `worker.py` — the actual LiveKit integration, only
    importable once the optional `voice` extra
    (`pip install -e ".[voice]"`) is installed. Importing `voice_orchestrator`
    itself never imports these two, so the CLI/tests/text-core keep working
    with nothing voice-related installed at all.
"""
