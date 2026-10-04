"""Audio-layer provider interfaces — VAD, end-of-speech, and noise
reduction — scaffolded as explicit attachment points for the real voice
layer this project's "core testuale prima" plan defers (see README's "What's
deliberately not here yet"). Nothing in this core's text pipeline calls
these yet; they exist so the eventual LiveKit/Deepgram/ElevenLabs
integration has a provider-swap pattern to slot into, consistent with
llm.py's LLMProvider and tools/base.py's Tool abstractions elsewhere in
this project.
"""
from .denoiser import DenoiserProvider, PassthroughDenoiser
from .end_of_speech import EndOfSpeechProvider, SilenceBasedEOS, TextModeEOS
from .vad import NoOpVAD, VADProvider

__all__ = [
    "VADProvider",
    "NoOpVAD",
    "EndOfSpeechProvider",
    "SilenceBasedEOS",
    "TextModeEOS",
    "DenoiserProvider",
    "PassthroughDenoiser",
]
