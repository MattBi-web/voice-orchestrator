"""STT and TTS instances from a resolved pipeline choice (blocco 8).

project.stt_for()/tts_for() decide *which* provider, model and voice an
agent uses; this module turns that choice into the livekit plugin object.
Each plugin is imported only when chosen, so a worker without, say, the
Cartesia plugin still runs every call that doesn't ask for it. A provider
whose plugin or key is missing raises here, at the start of the call or at
the handover, rather than failing silently: the catalog (catalog.py) is
what keeps the builder from offering it in the first place.
"""
from __future__ import annotations

import os

from .. import config
from ..project import Choice


def choice_key(choice: Choice) -> tuple:
    return (choice.component, choice.provider, choice.model, *sorted((k, str(v)) for k, v in choice.extra.items()))


def make_stt(choice: Choice):
    language = choice.extra.get("language") or "multi"
    if choice.provider == "deepgram":
        from livekit.plugins import deepgram

        return deepgram.STT(model=choice.model or "nova-3", language=language)
    if choice.provider == "openai":
        from livekit.plugins import openai

        if language == "multi":
            return openai.STT(model=choice.model or "gpt-4o-mini-transcribe", detect_language=True)
        return openai.STT(model=choice.model or "gpt-4o-mini-transcribe", language=language)
    if choice.provider == "assemblyai":
        from livekit.plugins import assemblyai

        model = choice.model or ("universal-streaming-english" if language == "en" else "universal-streaming-multilingual")
        return assemblyai.STT(model=model)
    raise ValueError(f"Unknown STT provider {choice.provider!r}")


def make_tts(choice: Choice):
    voice = choice.extra.get("voice_id") or ""
    stability = choice.extra.get("stability")
    speed = choice.extra.get("speed")
    if choice.provider == "elevenlabs":
        from livekit.plugins import elevenlabs

        kwargs: dict = {"model": choice.model or "eleven_flash_v2_5"}
        if voice:
            kwargs["voice_id"] = voice
        if stability is not None or speed is not None:
            settings: dict = {"stability": stability if stability is not None else 0.5, "similarity_boost": 0.75}
            if speed is not None:
                settings["speed"] = speed
            kwargs["voice_settings"] = elevenlabs.VoiceSettings(**settings)
        if config.ELEVENLABS_API_KEY:
            kwargs["api_key"] = config.ELEVENLABS_API_KEY
        return elevenlabs.TTS(**kwargs)
    if choice.provider == "openai":
        from livekit.plugins import openai

        return openai.TTS(model=choice.model or "gpt-4o-mini-tts", voice=voice or "alloy", speed=speed or 1.0)
    if choice.provider == "cartesia":
        from livekit.plugins import cartesia

        kwargs = {"model": choice.model or "sonic-3", "api_key": os.environ.get("CARTESIA_API_KEY")}
        if voice:
            kwargs["voice"] = voice
        return cartesia.TTS(**kwargs)
    raise ValueError(f"Unknown TTS provider {choice.provider!r}")
