"""D12, end to end in a real LiveKit room: a scripted caller speaks (audio
synthesized with ElevenLabs), Deepgram transcribes it, the local worker
(scripts/d12_local_worker.py, running voice/worker.py's entrypoint) routes
and answers with ElevenLabs, and the caller records what it hears.

    # terminal 1 — the family under test is in this file's FAMILY_YAML
    VOICE_ORCH_AGENTS_FILE=/tmp/d12_family.yaml python scripts/d12_local_worker.py start
    # terminal 2
    python scripts/d12_room_e2e.py /tmp/d12_family.yaml out_dir

(Run once with `--write-family` to create the YAML first.) Needs
LIVEKIT_URL/API_KEY/API_SECRET, DEEPGRAM_API_KEY, ELEVENLABS_API_KEY.

Checks: the greeting plays; after "ho un problema con la bolletta" the
reply comes in a different voice (median pitch of each reply, so the
check doesn't depend on reading any log); after "arrivederci" the room is
closed by the agent, and only after the farewell has finished. Fase C: the
call events the browser's call page is built from arrive on the data
channel (topic vo.events) in order: greeting, the billing turn decided by
the pattern level, the end_call turn, ended.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
import wave
from pathlib import Path

import numpy as np
from livekit import api, rtc
from livekit.agents.utils import http_context

from voice_orchestrator.voice.agent import elevenlabs_tts

sys.path.insert(0, str(Path(__file__).parent))
from d12_local_worker import AGENT_NAME  # noqa: E402

SR = 24000
FRAME = SR // 100  # 10 ms
BILLING_VOICE = "VR6AewLTigWG4xSOukaG"  # Arnold (male); the default voice is female
CALLER_VOICE = "pNInz6obpgDQGcFmaJgB"  # Adam

FAMILY_YAML = f"""root:
  id: router
  name: "Centralino"
  description: "Smista le chiamate."
  first_message: "Centralino, buongiorno. Come posso aiutarla?"
  children:
    - id: billing
      name: "Fatturazione"
      description: "Bollette e pagamenti."
      triggers: ["bollett"]
      tools: ["end_call"]
      voice_id: "{BILLING_VOICE}"
    - id: sales
      name: "Vendite"
      description: "Offerte."
      triggers: ["offert"]
"""


async def synth(text: str) -> np.ndarray:
    tts = elevenlabs_tts(voice_id=CALLER_VOICE)
    frames = []
    async for ev in tts.synthesize(text):
        frames.append(ev.frame)
    pcm = np.concatenate([np.frombuffer(bytes(f.data), dtype=np.int16) for f in frames])
    src_sr = frames[0].sample_rate
    if src_sr != SR:  # linear resample, good enough for STT
        idx = np.linspace(0, len(pcm) - 1, int(len(pcm) * SR / src_sr))
        pcm = np.interp(idx, np.arange(len(pcm)), pcm).astype(np.int16)
    return pcm


def f0_median(x: np.ndarray, sr: int) -> float:
    x = x.astype(float)
    win, out = int(0.04 * sr), []
    for i in range(0, len(x) - win, win):
        s = x[i : i + win]
        if np.sqrt(np.mean(s**2)) < 500:
            continue
        s = s - s.mean()
        ac = np.correlate(s, s, "full")[win - 1 :]
        lo, hi = int(sr / 400), int(sr / 70)
        lag = lo + int(np.argmax(ac[lo:hi]))
        if ac[lag] > 0.3 * ac[0]:
            out.append(sr / lag)
    return float(np.median(out)) if out else float("nan")


class Caller:
    def __init__(self) -> None:
        self.heard: list[tuple[float, np.ndarray]] = []  # (arrival time, 10ms chunk)
        self.speech: list[np.ndarray] = []
        self.disconnected_at: float | None = None
        self.last_voice_at = 0.0
        self.events: list[dict] = []

    async def feed(self, source: rtc.AudioSource, stop: asyncio.Event) -> None:
        silence = np.zeros(FRAME, dtype=np.int16)
        t0, n = time.monotonic(), 0
        buf = np.zeros(0, dtype=np.int16)
        while not stop.is_set():
            if not len(buf) and self.speech:
                buf = self.speech.pop(0)
            chunk, buf = (buf[:FRAME], buf[FRAME:]) if len(buf) else (silence, buf)
            if len(chunk) < FRAME:
                chunk = np.pad(chunk, (0, FRAME - len(chunk)))
            await source.capture_frame(rtc.AudioFrame(chunk.tobytes(), SR, 1, FRAME))
            n += 1
            await asyncio.sleep(max(0, t0 + n * 0.01 - time.monotonic()))

    async def listen(self, track: rtc.Track) -> None:
        async for ev in rtc.AudioStream(track, sample_rate=SR, num_channels=1):
            x = np.frombuffer(bytes(ev.frame.data), dtype=np.int16)
            now = time.monotonic()
            self.heard.append((now, x))
            if np.sqrt(np.mean(x.astype(float) ** 2)) > 300:
                self.last_voice_at = now

    async def wait_quiet(self, quiet: float = 1.5, timeout: float = 30) -> None:
        """Until the agent has spoken and then been silent for `quiet` s."""
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            if self.last_voice_at > start and time.monotonic() - self.last_voice_at > quiet:
                return
            await asyncio.sleep(0.1)
        raise TimeoutError("l'agente non ha risposto in tempo")

    def segments(self, gap: float = 0.8) -> list[tuple[float, float, np.ndarray]]:
        segs, cur, last = [], [], None
        for t, x in self.heard:
            loud = np.sqrt(np.mean(x.astype(float) ** 2)) > 300
            if loud:
                if last is not None and t - last > gap and cur:
                    segs.append(cur)
                    cur = []
                cur.append((t, x))
                last = t
            elif cur:
                cur.append((t, x))
        if cur:
            segs.append(cur)
        out = []
        for s in segs:
            loud_ts = [t for t, x in s if np.sqrt(np.mean(x.astype(float) ** 2)) > 300]
            out.append((loud_ts[0], loud_ts[-1], np.concatenate([x for _, x in s])))
        return out


async def main(out_dir: Path) -> int:
    url = os.environ["LIVEKIT_URL"]
    room_name = f"d12-e2e-{uuid.uuid4().hex[:6]}"
    lk = api.LiveKitAPI()
    await lk.room.create_room(api.CreateRoomRequest(name=room_name, empty_timeout=60))
    await lk.agent_dispatch.create_dispatch(api.CreateAgentDispatchRequest(agent_name=AGENT_NAME, room=room_name))

    async with http_context.open():
        utter_billing = await synth("Buongiorno, ho un problema con la bolletta.")
        utter_bye = await synth("Va bene, arrivederci.")

    caller = Caller()
    room = rtc.Room()
    agent_track: asyncio.Future = asyncio.get_running_loop().create_future()

    @room.on("track_subscribed")
    def _on_track(track, pub, participant):
        if track.kind == rtc.TrackKind.KIND_AUDIO and not agent_track.done():
            agent_track.set_result(track)

    @room.on("data_received")
    def _on_data(packet: rtc.DataPacket):
        if packet.topic == "vo.events":
            caller.events.append(json.loads(packet.data.decode("utf-8")))

    @room.on("disconnected")
    def _on_disc(reason):
        caller.disconnected_at = time.monotonic()

    token = (
        api.AccessToken().with_identity("caller").with_grants(api.VideoGrants(room_join=True, room=room_name)).to_jwt()
    )
    await room.connect(url, token)
    source = rtc.AudioSource(SR, 1)
    await room.local_participant.publish_track(
        rtc.LocalAudioTrack.create_audio_track("mic", source),
        rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE),
    )
    stop = asyncio.Event()
    feeder = asyncio.create_task(caller.feed(source, stop))
    track = await asyncio.wait_for(agent_track, timeout=30)
    listener = asyncio.create_task(caller.listen(track))

    print("attendo il saluto…")
    await caller.wait_quiet()
    print("dico: bolletta")
    caller.speech.append(utter_billing)
    await caller.wait_quiet(timeout=40)
    print("dico: arrivederci")
    caller.speech.append(utter_bye)
    t_bye = time.monotonic()
    while caller.disconnected_at is None and time.monotonic() - t_bye < 40:
        await asyncio.sleep(0.1)
    stop.set()
    feeder.cancel()
    listener.cancel()
    await lk.aclose()

    segs = caller.segments()
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"segmenti di voce dell'agente: {len(segs)}")
    pitches = []
    for i, (a, b, pcm) in enumerate(segs):
        f0 = f0_median(pcm, SR)
        pitches.append(f0)
        with wave.open(str(out_dir / f"room_{i:02d}.wav"), "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(SR), w.writeframes(pcm.tobytes())
        print(f"  #{i}: {b - a:5.2f}s di voce, f0 mediana ≈ {f0:5.0f} Hz")
    if caller.disconnected_at and segs:
        print(f"stanza chiusa {caller.disconnected_at - segs[-1][1]:+.2f}s dopo la fine dell'ultima voce udita")

    kinds = [e["type"] for e in caller.events]
    turns = [e for e in caller.events if e["type"] == "turn"]
    print(f"eventi ricevuti: {kinds}")
    checks = {
        "saluto + 2 risposte udite": len(segs) >= 3,
        "voce cambiata dopo l'handoff (f0 saluto vs risposta billing differisce >40 Hz)": len(pitches) >= 2
        and abs(pitches[0] - pitches[1]) > 40,
        "stanza chiusa dall'agente": caller.disconnected_at is not None,
        "chiusa dopo la fine del saluto": bool(segs) and caller.disconnected_at is not None
        and caller.disconnected_at >= segs[-1][1],
        "eventi: saluto, 2 turni, fine (in ordine)": kinds == ["greeting", "turn", "turn", "ended"],
        "evento turno billing: pattern, parola chiave, handoff": bool(turns)
        and turns[0]["agent_id"] == "billing"
        and turns[0]["resolved_by"] == "pattern"
        and turns[0]["keyword"] == "bollett"
        and turns[0]["handed_off"] is True,
        "evento turno arrivederci: end_call": len(turns) > 1 and "end_call" in turns[1]["tools"],
    }
    for name, ok in checks.items():
        print(f"[{'OK' if ok else 'FALLITO'}] {name}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    if "--write-family" in sys.argv:
        Path(sys.argv[2]).write_text(FAMILY_YAML, encoding="utf-8")
        print("scritto", sys.argv[2])
        sys.exit(0)
    sys.exit(asyncio.run(main(Path(sys.argv[2]) if len(sys.argv) > 2 else Path("d12_room_out"))))
