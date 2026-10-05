"""Runs voice/worker.py's exact entrypoint under an explicit agent name, so
a test room can dispatch to *this* process and not to a deployed worker
registered on the same LiveKit project (automatic dispatch would pick any).
Used by scripts/d12_room_e2e.py:

    python scripts/d12_local_worker.py start
"""
from livekit.agents import WorkerOptions, cli

from voice_orchestrator.voice.worker import entrypoint, request_fnc

AGENT_NAME = "voice-orchestrator-d12-local"

if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(entrypoint_fnc=entrypoint, request_fnc=request_fnc, agent_name=AGENT_NAME, num_idle_processes=0)
    )
