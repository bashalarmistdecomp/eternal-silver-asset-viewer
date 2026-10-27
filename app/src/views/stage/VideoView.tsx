import { LoaderCircle, Pause, Play, RotateCcw, Volume2, VolumeX } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type VideoInfo } from '../../lib/api'
import { audioContext, claimSpace } from '../../lib/keys'
import { transport } from '../../lib/transport'
import { cn, formatTime } from '../../lib/utils'
import { ToolButton } from './PixelView'

/** Seconds of movie kept decoded ahead of the playhead. */
const LEAD = 2.5
/** Sectors per request: one second at 2x CD speed. */
const CHUNK = 150
/** Scheduling slack between asking to start and the first sample. */
const START_DELAY = 0.15

type Scale = 'fit' | 1 | 2 | 3

interface Queued {
  t: number
  bitmap: ImageBitmap
}

/**
 * An STR movie, played from chunks the backend decodes on request
 * (viewer_server/video.py). The disc is the clock: sector N plays at
 * N/150 s for both tracks, so video frames are drawn against the time the
 * scheduled AUDIO has reached — Web Audio's clock — and stay in sync
 * without negotiating.
 */
export function VideoView({ sid, video, label }: { sid: string; video: VideoInfo; label: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const boxRef = useRef<HTMLDivElement>(null)
  const [playing, setPlaying] = useState(false)
  const [buffering, setBuffering] = useState(true)
  const [pos, setPos] = useState(0)
  const [size, setSize] = useState<{ w: number; h: number } | null>(null)
  const [audioDesc, setAudioDesc] = useState<string | null>(null)
  const [muted, setMuted] = useState(false)
  const [scale, setScale] = useState<Scale>('fit')
  // A movie is video, not pixel art: scaled up, it is filtered by default.
  const [smooth, setSmooth] = useState(true)
  // Shown as the game shows it on a TV, where the program says how; the
  // switch gives back the raw, square pixels.
  const [shaped, setShaped] = useState(true)
  const [box, setBox] = useState({ w: 640, h: 480 })
  const [error, setError] = useState<string | null>(null)
  const [scrubbing, setScrubbing] = useState<number | null>(null)

  // Everything the loops share lives in one ref, reset on every seek.
  const st = useRef({
    gen: 0,
    base: 0, // movie seconds at the clock origin
    t0: 0, // AudioContext time of the clock origin
    started: false, // the clock holds at `base` until the first chunk lands
    sector: 0,
    done: false,
    fetching: false,
    failed: false, // a chunk failed: none is asked for again until a play or a seek
    frames: [] as Queued[],
    audioAt: 0, // movie seconds the next audio buffer starts at
    sources: [] as AudioBufferSourceNode[],
    gain: null as GainNode | null,
  })

  const clock = useCallback(() => {
    const s = st.current
    if (!s.started) return s.base
    const ctx = audioContext()
    return Math.max(s.base, Math.min(video.duration, s.base + ctx.currentTime - s.t0))
  }, [video.duration])

  const pump = useCallback(async () => {
    const s = st.current
    const gen = s.gen
    if (s.fetching || s.done || s.failed) return
    s.fetching = true
    try {
      while (gen === s.gen && !s.done && s.sector / video.sectorsPerSecond - clock() < LEAD) {
        const c = await api.videoChunk(sid, video.id, s.sector, CHUNK)
        if (gen !== s.gen) return
        s.sector = c.next
        s.done = c.done
        const ctx = audioContext()
        if (!s.started) {
          // Start the clock now, not when asked: the first chunk takes about
          // half a second to decode, and a clock already running would have
          // made its audio and frames late before they arrived.
          s.t0 = ctx.currentTime + START_DELAY
          s.started = true
        }
        if (c.audio) {
          const pcm = Uint8Array.from(atob(c.audio.pcm), (ch) => ch.charCodeAt(0))
          const view = new DataView(pcm.buffer)
          const chans = c.audio.channels
          const n = pcm.length / 2 / chans
          if (n > 0) {
            const buf = ctx.createBuffer(chans, n, c.audio.rate)
            for (let ch = 0; ch < chans; ch++) {
              const out = buf.getChannelData(ch)
              for (let i = 0; i < n; i++) out[i] = view.getInt16((i * chans + ch) * 2, true) / 32768
            }
            const src = ctx.createBufferSource()
            src.buffer = buf
            src.connect(s.gain!)
            const at = s.t0 + (s.audioAt - s.base)
            // A buffer that arrives late starts part-way in, so it stays in
            // step with the frames rather than pushing every later one back.
            const now = ctx.currentTime
            if (at >= now) src.start(at)
            else if (now - at < buf.duration) src.start(now, now - at)
            s.audioAt += buf.duration
            s.sources.push(src)
            src.onended = () => {
              s.sources = s.sources.filter((x) => x !== src)
            }
            setAudioDesc(`XA ${chans === 2 ? 'stereo' : 'mono'} ${c.audio.rate.toLocaleString()} Hz`)
          }
        }
        for (const f of c.frames) {
          const bytes = Uint8Array.from(atob(f.png), (ch) => ch.charCodeAt(0))
          const bitmap = await createImageBitmap(new Blob([bytes], { type: 'image/png' }))
          if (gen !== s.gen) {
            bitmap.close()
            return
          }
          s.frames.push({ t: f.t, bitmap })
          setSize((old) => (old && old.w === f.w && old.h === f.h ? old : { w: f.w, h: f.h }))
        }
        setBuffering(false)
      }
    } catch (e) {
      if (gen === s.gen) {
        // it stands where it failed: Play, or a seek, asks again
        s.failed = true
        setError(e instanceof Error ? e.message : String(e))
        void audioContext().suspend()
        setPlaying(false)
      }
    } finally {
      if (gen === s.gen) s.fetching = false
    }
  }, [sid, video, clock])

  const start = useCallback(
    (at: number) => {
      const s = st.current
      const ctx = audioContext()
      s.gen++
      for (const src of s.sources) {
        try {
          src.stop()
        } catch {
          // already ended
        }
      }
      s.sources = []
      for (const f of s.frames) f.bitmap.close()
      s.frames = []
      if (!s.gain) {
        s.gain = ctx.createGain()
        s.gain.connect(ctx.destination)
      }
      s.base = Math.max(0, Math.min(at, video.duration - 0.1))
      s.sector = Math.floor(s.base * video.sectorsPerSecond)
      s.audioAt = s.base
      s.t0 = ctx.currentTime + START_DELAY
      s.started = false
      s.done = false
      s.fetching = false
      s.failed = false
      setError(null)
      setBuffering(true)
      void pump()
    },
    [pump, video],
  )

  // A movie opens playing, and the audio
  // transport makes way for it.
  useEffect(() => {
    transport.pause()
    start(0)
    void audioContext().resume()
    setPlaying(true)
    const s = st.current
    return () => {
      s.gen++
      for (const src of s.sources) {
        try {
          src.stop()
        } catch {
          // already ended
        }
      }
      for (const f of s.frames) f.bitmap.close()
      s.frames = []
      void audioContext().resume()
    }
  }, [video.id, start])

  useEffect(() => {
    const g = st.current.gain
    if (g) g.gain.value = muted ? 0 : 1
  }, [muted])

  const toggle = useCallback(() => {
    const ctx = audioContext()
    if (playing) {
      void ctx.suspend()
      setPlaying(false)
    } else {
      transport.pause()
      if (clock() >= video.duration - 0.05) start(0)
      else if (st.current.failed) start(clock())
      void ctx.resume()
      setPlaying(true)
    }
  }, [playing, clock, start, video.duration])

  useEffect(() => claimSpace(toggle), [toggle])

  // Draw loop: the newest frame due by the clock. Frames that fell behind
  // are dropped, never shown late, so the picture keeps time with the sound.
  useEffect(() => {
    let raf = 0
    let lastPos = -1
    const tick = () => {
      const s = st.current
      const p = clock()
      let newest: Queued | null = null
      while (s.frames.length && s.frames[0].t <= p) {
        if (newest) newest.bitmap.close()
        newest = s.frames.shift()!
      }
      const canvas = canvasRef.current
      if (newest && canvas) {
        if (canvas.width !== newest.bitmap.width || canvas.height !== newest.bitmap.height) {
          canvas.width = newest.bitmap.width
          canvas.height = newest.bitmap.height
        }
        canvas.getContext('2d')!.drawImage(newest.bitmap, 0, 0)
        newest.bitmap.close()
      }
      if (Math.abs(p - lastPos) > 0.05) {
        lastPos = p
        setPos(p)
      }
      void pump()
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [clock, pump])

  useEffect(() => {
    const el = boxRef.current
    if (!el) return
    const ro = new ResizeObserver(() => setBox({ w: el.clientWidth, h: el.clientHeight }))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const fw = size?.w ?? 320
  const fh = size?.h ?? 240
  const par = video.pixelAspect
  const wide = shaped && par ? par[0] / par[1] : 1
  const room = Math.min((box.w - 32) / (fw * wide), (box.h - 32) / fh)
  // Filtered, any size fills the stage; sharp pixels keep to whole multiples.
  const fit = smooth ? Math.max(0.25, room) : Math.max(1, Math.floor(room))
  const z = scale === 'fit' ? fit : scale
  const shapeLabel = par ? pictureShape(fw * par[0], fh * par[1]) : null

  return (
    <div className="flex-1 min-w-0 min-h-0 flex flex-col bg-stage">
      <div ref={boxRef} className="flex-1 min-h-0 overflow-auto stage-scroll flex items-center justify-center relative">
        <canvas
          ref={canvasRef}
          width={fw}
          height={fh}
          className={cn('bg-black shadow-xl', !smooth && 'pixelated')}
          style={{ width: Math.round(fw * wide * z), height: Math.round(fh * z) }}
        />
        {(buffering || error) && (
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
            <div className="rounded-md bg-black/70 px-3 py-2 text-xs text-stage-foreground flex items-center gap-2">
              {error ? (
                <span className="text-red-300">{error}</span>
              ) : (
                <>
                  <LoaderCircle className="w-3.5 h-3.5 animate-spin" /> Decoding {label}…
                </>
              )}
            </div>
          </div>
        )}
      </div>
      <div className="h-11 shrink-0 bg-stage-raised border-t border-stage-border flex items-center gap-2 px-3 text-stage-foreground">
        <ToolButton title={playing ? 'Pause (Space)' : 'Play (Space)'} onClick={toggle}>
          {playing ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
        </ToolButton>
        <ToolButton
          title="Restart"
          onClick={() => {
            start(0)
            void audioContext().resume()
            setPlaying(true)
          }}
        >
          <RotateCcw className="w-3.5 h-3.5" />
        </ToolButton>
        <span className="text-[11px] font-mono w-28 shrink-0">
          {formatTime(scrubbing ?? pos)} <span className="text-stage-muted">/ {formatTime(video.duration)}</span>
        </span>
        <input
          type="range"
          min={0}
          max={video.duration}
          step={0.1}
          value={scrubbing ?? pos}
          onChange={(e) => setScrubbing(Number(e.target.value))}
          onPointerUp={() => {
            if (scrubbing !== null) {
              start(scrubbing)
              setScrubbing(null)
              if (playing) void audioContext().resume()
            }
          }}
          onKeyUp={() => {
            if (scrubbing !== null) {
              start(scrubbing)
              setScrubbing(null)
            }
          }}
          className="flex-1 accent-primary cursor-pointer"
          title="Seek"
        />
        <ToolButton title={muted ? 'Unmute' : 'Mute'} onClick={() => setMuted((m) => !m)}>
          {muted ? <VolumeX className="w-3.5 h-3.5" /> : <Volume2 className="w-3.5 h-3.5" />}
        </ToolButton>
        <span className={cn('text-[11px] truncate max-w-64', video.fromImage ? 'text-stage-muted' : 'text-amber-300')} title={video.note}>
          {video.fromImage ? (audioDesc ?? 'from the disc image') : 'video only — no disc image'}
        </span>
        <div className="flex gap-0.5">
          {par && shapeLabel && (
            <button
              onClick={() => setShaped((v) => !v)}
              title={
                shaped
                  ? `As the game shows it: ${video.shapeNote}. Click for raw pixels.`
                  : `Raw pixels, shown square. Click to show it as the game does (${shapeLabel}).`
              }
              className={cn(
                'h-6 px-1.5 rounded text-[10px] font-mono cursor-pointer',
                shaped ? 'bg-primary text-primary-foreground' : 'text-stage-muted hover:text-stage-foreground',
              )}
            >
              {shapeLabel}
            </button>
          )}
          <button
            onClick={() => setSmooth((v) => !v)}
            title={smooth ? 'Scaled smoothly — click for sharp pixels' : 'Sharp pixels — click to scale smoothly'}
            className={cn(
              'h-6 px-1.5 rounded text-[10px] font-mono cursor-pointer',
              smooth ? 'bg-primary text-primary-foreground' : 'text-stage-muted hover:text-stage-foreground',
            )}
          >
            smooth
          </button>
          {(['fit', 1, 2, 3] as Scale[]).map((s) => (
            <button
              key={String(s)}
              onClick={() => setScale(s)}
              className={cn(
                'h-6 px-1.5 rounded text-[10px] font-mono cursor-pointer',
                scale === s ? 'bg-primary text-primary-foreground' : 'text-stage-muted hover:text-stage-foreground',
              )}
            >
              {s === 'fit' ? 'fit' : `${s}×`}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

/** A picture's shape as "4:3", from its width and height in any unit. */
function pictureShape(w: number, h: number): string {
  for (let d = 1; d <= 16; d++) {
    const n = (w / h) * d
    if (Math.abs(n - Math.round(n)) < 1e-6) return `${Math.round(n)}:${d}`
  }
  return `${(w / h).toFixed(2)}:1`
}
