"""Noise reduction — a third separate pluggable audio concern (Rapida's
`denoiser` package), applied to raw audio frames before they reach STT/VAD.
Scaffolded here for the same reason as vad.py/end_of_speech.py: a documented
attachment point for the real voice layer, not an implementation — this
core has no audio to denoise yet.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class DenoiserProvider(ABC):
    @abstractmethod
    def denoise(self, frame: bytes, sample_rate: int) -> bytes:
        """Returns a cleaned copy of `frame`. A real provider would wrap
        something like RNNoise or a vendor-specific model."""
        ...


class PassthroughDenoiser(DenoiserProvider):
    """Returns the frame unchanged — the correct default until a real
    denoiser is configured, and the right choice on a channel (e.g. a SIP
    trunk) where the upstream telephony provider already denoises."""

    def denoise(self, frame: bytes, sample_rate: int) -> bytes:
        return frame
