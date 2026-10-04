"""End-of-speech detection — deliberately separate from VAD (vad.py), the
same split Rapida's platform validated in production (silence_based_eos and
livekit_eos as providers distinct from silero_vad/ten_vad). A VAD says "is
there voice in this frame right now"; an EOS provider says "has the caller
finished their turn" — which needs more than frame-level activity: a pause
long enough to be a pause and not a breath, and, in a smarter provider,
whether the transcript-so-far sounds grammatically complete.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class EndOfSpeechProvider(ABC):
    @abstractmethod
    def is_end_of_speech(self, transcript_so_far: str, silence_ms: float) -> bool:
        """True once the caller's turn should be considered over and handed
        to the router/LLM. `transcript_so_far` is what STT has produced
        since the caller started talking; `silence_ms` is how long it's
        been quiet since the last word."""
        ...


class SilenceBasedEOS(EndOfSpeechProvider):
    """The simplest real EOS strategy (Rapida's silence_based_eos): the turn
    is over once silence has lasted past a threshold. No grammar or semantic
    awareness — a reasonable default, and the baseline a smarter provider
    (an endpointing-model-based one, like LiveKit's) should beat before it's
    worth the extra latency or cost."""

    def __init__(self, threshold_ms: float = 700.0):
        self.threshold_ms = threshold_ms

    def is_end_of_speech(self, transcript_so_far: str, silence_ms: float) -> bool:
        return bool(transcript_so_far.strip()) and silence_ms >= self.threshold_ms


class TextModeEOS(EndOfSpeechProvider):
    """For a typed utterance (this project's CLI/eval, today) there's no
    streaming silence to measure — the turn ends when the caller hits enter.
    Always true, so text-mode callers of this interface don't need a
    special case elsewhere in the code."""

    def is_end_of_speech(self, transcript_so_far: str, silence_ms: float) -> bool:
        return True
