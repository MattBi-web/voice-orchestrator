"""Voice Activity Detection — one of three audio-layer concerns this project
scaffolds as an explicit attachment point for the real voice layer (see
end_of_speech.py, denoiser.py, and this package's __init__.py docstring).
Rapida keeps VAD as its own pluggable provider, separate from end-of-speech
(silero_vad/ten_vad vs. silence_based_eos/livekit_eos) — a split validated by
a real production system, not just our own guess, so it's worth keeping even
though there's no real audio frame to feed it yet.

A VADProvider answers one question per audio frame: is the caller speaking
right now? It says nothing about whether they're DONE speaking — that's
end_of_speech.py's job. Conflating the two is exactly the mistake Rapida's
separation avoids: a VAD can flicker on background noise or a breath, while
"the turn is over" needs more context than one frame's voice activity.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class VADProvider(ABC):
    @abstractmethod
    def is_speech(self, frame: bytes, sample_rate: int) -> bool:
        """True if `frame` (raw PCM) contains speech. In a real pipeline
        this is called once per audio frame (e.g. every 20-30ms); not
        implemented here, since this core is text-only — a real provider
        would wrap something like Silero or TEN VAD."""
        ...


class NoOpVAD(VADProvider):
    """Always reports speech. The correct default for a text-only pipeline
    (there's no silence to detect in a typed utterance) and a safe fallback
    if a real VAD provider isn't configured yet."""

    def is_speech(self, frame: bytes, sample_rate: int) -> bool:
        return True
