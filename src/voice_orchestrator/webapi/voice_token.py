"""Mints a LiveKit room token for the agent-builder's browser-based live
voice test console (web/src/components/VoiceTestConsole.tsx) — the same
mechanism LiveKit's own hosted Agents Playground uses: a short-lived JWT
scoped to one freshly-named room, handed to livekit-client in the browser.
Signing a JWT from the API key/secret pair is a local, offline operation
(livekit-api's AccessToken) — no network call to LiveKit happens here.

The worker (voice/worker.py) still has to be running separately
(`python -m voice_orchestrator.voice.worker dev`) for anything to actually
join the room and respond; by default a LiveKit Agents worker auto-dispatches
to any newly-created room, the exact mechanism the hosted Playground relies
on — this module only issues the ticket, like the Playground's own backend
does, not a dispatch.
"""
from __future__ import annotations

import secrets

from livekit import api

from .. import config


def is_configured() -> bool:
    return bool(config.LIVEKIT_URL and config.LIVEKIT_API_KEY and config.LIVEKIT_API_SECRET)


def mint() -> dict:
    """Returns {"token", "url", "room", "identity"} for a fresh, randomly
    named room — one new room per test session, so two people trying the
    console at once don't end up dropped into the same call."""
    identity = f"web-tester-{secrets.token_hex(3)}"
    room_name = f"webtest-{secrets.token_hex(4)}"
    grants = api.VideoGrants(room_join=True, room=room_name, can_publish=True, can_subscribe=True)
    token = (
        api.AccessToken(config.LIVEKIT_API_KEY, config.LIVEKIT_API_SECRET)
        .with_identity(identity)
        .with_name(identity)
        .with_grants(grants)
        .to_jwt()
    )
    return {"token": token, "url": config.LIVEKIT_URL, "room": room_name, "identity": identity}
