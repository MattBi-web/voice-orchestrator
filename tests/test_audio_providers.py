"""The audio-layer interfaces (audio/) have no real audio to process yet —
these tests just pin down the reference implementations' documented
behavior, so a future real provider (Silero VAD, LiveKit EOS, RNNoise...)
has a contract to match."""
from voice_orchestrator.audio import (
    NoOpVAD,
    PassthroughDenoiser,
    SilenceBasedEOS,
    TextModeEOS,
)


def test_noop_vad_always_reports_speech():
    vad = NoOpVAD()
    assert vad.is_speech(frame=b"\x00" * 320, sample_rate=16000) is True
    assert vad.is_speech(frame=b"", sample_rate=16000) is True


def test_passthrough_denoiser_returns_frame_unchanged():
    denoiser = PassthroughDenoiser()
    frame = b"\x01\x02\x03"
    assert denoiser.denoise(frame, sample_rate=16000) is frame


def test_silence_based_eos_waits_for_threshold():
    eos = SilenceBasedEOS(threshold_ms=700.0)
    assert eos.is_end_of_speech("ciao come stai", silence_ms=200.0) is False
    assert eos.is_end_of_speech("ciao come stai", silence_ms=700.0) is True
    assert eos.is_end_of_speech("ciao come stai", silence_ms=1500.0) is True


def test_silence_based_eos_requires_a_nonempty_transcript():
    # Silence with nothing transcribed yet isn't an end-of-turn — it's
    # just... silence (the caller hasn't started talking).
    eos = SilenceBasedEOS(threshold_ms=700.0)
    assert eos.is_end_of_speech("", silence_ms=5000.0) is False
    assert eos.is_end_of_speech("   ", silence_ms=5000.0) is False


def test_text_mode_eos_always_true():
    eos = TextModeEOS()
    assert eos.is_end_of_speech("qualunque cosa", silence_ms=0.0) is True
    assert eos.is_end_of_speech("", silence_ms=0.0) is True
