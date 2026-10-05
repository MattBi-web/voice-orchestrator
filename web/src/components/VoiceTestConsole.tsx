import { useEffect, useRef, useState } from 'react'
import {
  Room,
  RoomEvent,
  Track,
  type Participant,
  type RemoteParticipant,
  type RemoteTrack,
  type RemoteTrackPublication,
  type TranscriptionSegment,
} from 'livekit-client'
import { api, ApiError } from '../api'

type Status = 'idle' | 'connecting' | 'connected' | 'error'

interface TranscriptLine {
  id: string
  speaker: string
  text: string
  final: boolean
}

/** The real thing, not a simulation: mints a LiveKit room token from the
 * backend (POST /api/voice/token — same mechanism the hosted Agents
 * Playground's own backend uses), joins that room with the browser's
 * microphone via livekit-client, and plays back whatever audio the running
 * worker (`python -m voice_orchestrator.voice.worker dev`) publishes in
 * return. This component only ever talks to LiveKit directly — it has no
 * idea the orchestrator, routing, or tools exist; that's the whole point,
 * the same separation the CLI's `chat` and the voice worker already have. */
export function VoiceTestConsole() {
  const [configured, setConfigured] = useState<boolean | null>(null)
  const [status, setStatus] = useState<Status>('idle')
  const [error, setError] = useState<string | null>(null)
  const [, setRoomName] = useState<string | null>(null)
  const [transcript, setTranscript] = useState<TranscriptLine[]>([])
  const roomRef = useRef<Room | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)

  useEffect(() => {
    api
      .getVoiceStatus()
      .then((s) => setConfigured(s.configured))
      .catch(() => setConfigured(false))
    return () => {
      roomRef.current?.disconnect()
    }
  }, [])

  const connect = async () => {
    setError(null)
    setStatus('connecting')
    setTranscript([])
    try {
      const { token, url, room: newRoomName } = await api.getVoiceToken()
      const room = new Room()
      roomRef.current = room
      setRoomName(newRoomName)

      room.on(RoomEvent.TrackSubscribed, (track: RemoteTrack, _pub: RemoteTrackPublication, _participant: RemoteParticipant) => {
        if (track.kind === Track.Kind.Audio && audioRef.current) {
          track.attach(audioRef.current)
        }
      })

      room.on(RoomEvent.TranscriptionReceived, (segments: TranscriptionSegment[], participant?: Participant) => {
        setTranscript((prev) => {
          const next = [...prev]
          for (const seg of segments) {
            const speaker = participant ? participant.identity : 'tu'
            const idx = next.findIndex((l) => l.id === seg.id)
            const line: TranscriptLine = { id: seg.id, speaker, text: seg.text, final: seg.final }
            if (idx >= 0) next[idx] = line
            else next.push(line)
          }
          return next
        })
      })

      room.on(RoomEvent.Disconnected, () => {
        setStatus('idle')
        setRoomName(null)
      })

      await room.connect(url, token)
      await room.localParticipant.setMicrophoneEnabled(true)
      setStatus('connected')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
      setStatus('error')
      roomRef.current?.disconnect()
      roomRef.current = null
    }
  }

  const disconnect = () => {
    roomRef.current?.disconnect()
    roomRef.current = null
    setStatus('idle')
    setRoomName(null)
  }

  return (
    <div className="voice-console">
      <p className="voice-console__hint">
        Uses your microphone. The demo agents speak Italian: try asking about your bill, roaming, or a slow
        connection, and say "arrivederci" to end the call.
      </p>

      {configured === false && (
        <p className="error">
          Voice calls aren't set up on this server: LiveKit credentials are missing.
        </p>
      )}

      {error && <p className="error">{error}</p>}

      <div className="voice-console__controls">
        {status !== 'connected' ? (
          <button type="button" onClick={connect} disabled={configured !== true || status === 'connecting'}>
            {status === 'connecting' ? 'Connecting…' : 'Start call'}
          </button>
        ) : (
          <button type="button" className="btn-danger" onClick={disconnect}>
            End call
          </button>
        )}
        {status === 'connected' && <span className="voice-console__status">● On a call</span>}
      </div>

      {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
      <audio ref={audioRef} autoPlay />

      {transcript.length > 0 && (
        <div className="voice-console__transcript">
          {transcript.map((line) => (
            <p key={line.id} className={line.final ? 'voice-console__line' : 'voice-console__line voice-console__line--partial'}>
              <strong>{line.speaker}:</strong> {line.text}
            </p>
          ))}
        </div>
      )}
    </div>
  )
}
