"""config.py's env parsing — an empty-but-set variable (a `NAME=` line in a
sourced .env) must fall back to the default, not crash the import."""
from voice_orchestrator.config import _env_float


def test_env_float_empty_counts_as_unset(monkeypatch):
    monkeypatch.setenv("VOICE_ORCH_TEST_FLOAT", "")
    assert _env_float("VOICE_ORCH_TEST_FLOAT", 60.0) == 60.0
    monkeypatch.setenv("VOICE_ORCH_TEST_FLOAT", "  ")
    assert _env_float("VOICE_ORCH_TEST_FLOAT", 60.0) == 60.0


def test_env_float_reads_a_real_value(monkeypatch):
    monkeypatch.setenv("VOICE_ORCH_TEST_FLOAT", "12.5")
    assert _env_float("VOICE_ORCH_TEST_FLOAT", 60.0) == 12.5
    monkeypatch.delenv("VOICE_ORCH_TEST_FLOAT")
    assert _env_float("VOICE_ORCH_TEST_FLOAT", 60.0) == 60.0
