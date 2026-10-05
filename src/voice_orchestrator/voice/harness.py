"""A scripted voice call without a room (D12): the real `AgentSession` and
the real `OrchestratorAgent`, driven by text turns
(`session.generate_reply(user_input=...)`) instead of a caller's speech,
with the audio captured by an in-memory output that plays it out in real
time instead of publishing it over WebRTC.

That's enough to check the two things D12 was about, end to end through
livekit-agents' own pipeline: which voice synthesized each reply after a
handoff, and that `end_call` hangs up only after the farewell has finished
playing. STT and VAD aren't involved (input is text), and neither is a
LiveKit server.

Used by tests/test_voice_agent.py with `FakeTTS` (no network, no keys) and
by scripts/d12_live_check.py with real ElevenLabs voices.
"""
from __future__ import annotations

import asyncio
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from livekit import rtc
from livekit.agents import AgentSession, tts
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, APIConnectOptions
from livekit.agents.utils import shortuuid
from livekit.agents.voice import io

from ..agents.registry import AgentSpec
from ..llm import FakeProvider
from ..state import CallSession
from .agent import OrchestratorAgent
from .bridge import VoiceBridge


@dataclass
class Synthesis:
    voice: str  # voice id (or "default" for the session's own TTS)
    text: str
    at: float


@dataclass
class Segment:
    frames: list[rtc.AudioFrame] = field(default_factory=list)
    started_at: float = 0.0
    finished_at: float | None = None
    interrupted: bool = False

    @property
    def duration(self) -> float:
        return sum(f.duration for f in self.frames)


class CaptureAudioOutput(io.AudioOutput):
    """Keeps every frame, and reports each segment as played out after its
    real audio duration — like a speaker would — so `wait_for_playout()`
    means what it means in a real call."""

    def __init__(self, speed: float = 1.0) -> None:
        super().__init__(label="capture", capabilities=io.AudioOutputCapabilities(pause=False))
        self.segments: list[Segment] = []
        self._current: Segment | None = None
        self._speed = speed
        self._tasks: set[asyncio.Task] = set()

    async def capture_frame(self, frame: rtc.AudioFrame) -> None:
        await super().capture_frame(frame)
        if self._current is None:
            self._current = Segment(started_at=time.monotonic())
            self.segments.append(self._current)
            self.on_playback_started(created_at=time.time())
        self._current.frames.append(frame)

    def flush(self) -> None:
        super().flush()
        seg, self._current = self._current, None
        if seg is None:
            return
        task = asyncio.create_task(self._play(seg))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _play(self, seg: Segment) -> None:
        await asyncio.sleep(seg.duration / self._speed)
        if seg.finished_at is None:
            seg.finished_at = time.monotonic()
            self.on_playback_finished(playback_position=seg.duration, interrupted=False)

    def clear_buffer(self) -> None:
        seg, self._current = self._current, None
        if seg is not None and seg.finished_at is None:
            seg.finished_at, seg.interrupted = time.monotonic(), True
            self.on_playback_finished(playback_position=seg.duration, interrupted=True)

    def write_wavs(self, directory: Path, names: list[str]) -> list[Path]:
        directory.mkdir(parents=True, exist_ok=True)
        out = []
        for i, (seg, name) in enumerate(zip(self.segments, names)):
            if not seg.frames:
                continue
            path = directory / f"{i:02d}_{name}.wav"
            first = seg.frames[0]
            with wave.open(str(path), "wb") as w:
                w.setnchannels(first.num_channels)
                w.setsampwidth(2)
                w.setframerate(first.sample_rate)
                for f in seg.frames:
                    w.writeframes(bytes(f.data))
            out.append(path)
        return out


class FakeTTS(tts.TTS):
    """Silence whose length follows the text (~60 ms per character), so
    playout timing is realistic without any network call."""

    def __init__(self, voice: str = "default", sample_rate: int = 24000) -> None:
        super().__init__(capabilities=tts.TTSCapabilities(streaming=False), sample_rate=sample_rate, num_channels=1)
        self.voice = voice

    def synthesize(self, text: str, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS) -> tts.ChunkedStream:
        return _FakeChunkedStream(tts=self, input_text=text, conn_options=conn_options)


class _FakeChunkedStream(tts.ChunkedStream):
    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        output_emitter.initialize(
            request_id=shortuuid(), sample_rate=self._tts.sample_rate, num_channels=1, mime_type="audio/pcm"
        )
        seconds = max(0.3, len(self._input_text) * 0.06)
        output_emitter.push(b"\x00\x00" * int(self._tts.sample_rate * seconds))
        output_emitter.flush()


def record_synthesis(instance: tts.TTS, voice: str, log: list[Synthesis]) -> tts.TTS:
    """Wraps one TTS instance so every synthesis it performs is logged with
    its voice — instance-level, so nothing else is affected."""
    orig_synth = instance.synthesize
    orig_stream = instance.stream

    def synthesize(text, **kw):
        log.append(Synthesis(voice, text, time.monotonic()))
        return orig_synth(text, **kw)

    def stream(**kw):
        stream_obj = orig_stream(**kw)
        orig_push = stream_obj.push_text
        state = {"logged": False}

        def push_text(token):
            if not state["logged"] and token.strip():
                log.append(Synthesis(voice, token, time.monotonic()))
                state["logged"] = True
            return orig_push(token)

        stream_obj.push_text = push_text
        return stream_obj

    instance.synthesize = synthesize
    instance.stream = stream
    return instance


@dataclass
class ScriptedCall:
    agent: OrchestratorAgent
    session: AgentSession
    output: CaptureAudioOutput
    syntheses: list[Synthesis]
    replies: list[tuple[str, str]]  # (agent id, reply text) per turn


async def run_scripted_call(*args, **kwargs) -> ScriptedCall:
    """Outside a worker job, plugins need an HTTP context opened explicitly
    (inside one, the worker provides it)."""
    from livekit.agents.utils import http_context

    async with http_context.open():
        return await _run_scripted_call(*args, **kwargs)


async def _run_scripted_call(
    root: AgentSpec,
    utterances: list[str],
    default_tts: tts.TTS,
    voice_factory: Callable[[AgentSpec], tts.TTS],
    default_voice_label: str = "default",
    playout_speed: float = 1.0,
) -> ScriptedCall:
    syntheses: list[Synthesis] = []
    record_synthesis(default_tts, default_voice_label, syntheses)
    bridge = VoiceBridge(session=CallSession(call_id="scripted", channel="voice"), root=root, provider=FakeProvider())
    agent = OrchestratorAgent(
        bridge, voice_factory=lambda spec: record_synthesis(voice_factory(spec), spec.voice_id, syntheses)
    )
    session = AgentSession(tts=default_tts)
    output = CaptureAudioOutput(speed=playout_speed)
    session.output.audio = output
    closed = asyncio.Event()
    session.on("close", lambda _ev: closed.set())
    await session.start(agent=agent)

    replies: list[tuple[str, str]] = []
    for utterance in utterances:
        if closed.is_set():
            break
        handle = session.generate_reply(user_input=utterance)
        await handle.wait_for_playout()
        last = bridge.session.full_log[-1]
        replies.append((last.agent_id or "", last.text))
    # A scheduled hangup closes the session itself once the farewell has
    # played; give it the time to. Otherwise close it here.
    if agent._hangup_scheduled:
        try:
            await asyncio.wait_for(closed.wait(), timeout=30)
        except asyncio.TimeoutError:
            pass
    if not closed.is_set():
        await session.aclose()
    return ScriptedCall(agent, session, output, syntheses, replies)
