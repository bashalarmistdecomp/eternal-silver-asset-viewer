import { ChevronDown, ChevronRight, Download, LoaderCircle, Pause, Play, RotateCcw } from 'lucide-react'
import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { LinkGroups } from '../../components/RefLink'
import type { LinkItem, Pan, Result } from '../../lib/api'
import { blobUrl } from '../../lib/backend'
import { claimSpace } from '../../lib/keys'
import { loadImage, pixels } from '../../lib/sceneImages'
import { usePlaySong } from '../../lib/songs'
import { transport, type Loaded } from '../../lib/transport'
import { formatTime } from '../../lib/utils'
import { ToolButton } from './PixelView'

/** Room around the show and the whole picture, in screen pixels. */
const PAD = 32
/** Between the show and the whole picture. */
const GAP = 20
/** The narrowest the whole picture is drawn beside the show. */
const THUMB = 112

/** Is the transport holding clip `id` (a bromide's voice, once played)? */
const holds = (id: string | null) => !!id && transport.state.loaded?.resultId === id

/** Is `l` voice `v` of `program`, as its row in Voices plays it (DiscView's playSong)? */
const isVoice = (l: Loaded, v: LinkItem, program?: string) =>
  l.source.startsWith('Voices · ') && l.title === v.title && l.program === program

/**
 * A picture the game shows by looking down it: a bromide (BromidesProvider).
 * The screen's window moves over the whole picture frame by frame, as the
 * game's code moves it (`pan.rows`), and the fade takes `pan.dark` off each
 * colour, as the screen fades in from black and out to black. Its voice
 * plays from the row that is its home (Voices), through the transport, and
 * starts with the first frame, as the game starts it. Beside the show, the
 * whole picture with the window on it; under it, the page: what it is, its
 * links, and the extended info (folded in Fan mode, open in Advanced).
 */
export function BromideView({
  result,
  pan,
  advanced,
  onExport,
}: {
  result: Result
  pan: Pan
  advanced: boolean
  onExport: (layer: number, all: boolean) => void
}) {
  const playSong = usePlaySong()
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const boxRef = useRef<HTMLDivElement>(null)
  const [box, setBox] = useState(640)
  const [src, setSrc] = useState<ImageData | null>(null)
  const [failed, setFailed] = useState(false)
  const [playing, setPlaying] = useState(false)
  const [frame, setFrame] = useState(0)
  const [asking, setAsking] = useState(false)
  // Not yet played or moved: the still shown is the first frame the fade has left alone.
  const [fresh, setFresh] = useState(true)
  const frames = pan.rows.length
  const seconds = frames / pan.hz
  const firstLit = useMemo(() => Math.max(0, pan.dark.findIndex((d) => d === 0)), [pan.dark])
  const st = useRef({ t: 0, last: 0, playing: false, fresh: true, voice: null as string | null })

  const page = result.page
  const voice: LinkItem | null = useMemo(() => {
    for (const g of page?.groups ?? []) if (g.dir === 'out') for (const l of g.links) if (l.ref.kind === 'voice') return l
    return null
  }, [page])
  const disc = result.disc ?? result.tags[0] ?? ''

  // Keyed by its result (Stage), the view reads its picture once.
  useEffect(() => {
    let live = true
    loadImage(pan.blob)
      .then((im) => {
        if (!live) return
        const px = pixels(im)
        if (px) setSrc(px)
        else setFailed(true)
      })
      .catch(() => live && setFailed(true))
    return () => {
      live = false
    }
  }, [pan.blob])

  useEffect(() => {
    const el = boxRef.current
    if (!el) return
    const ro = new ResizeObserver(() => setBox(el.clientWidth))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const draw = useCallback(
    (f: number) => {
      const c = canvasRef.current
      if (!c || !src) return
      const g = c.getContext('2d')!
      const out = g.createImageData(pan.screenW, pan.screenH)
      const row = pan.rows[f] ?? 0
      const dark = pan.dark[f] ?? 0
      const from = src.data
      const to = out.data
      const w = Math.min(pan.screenW, src.width)
      for (let y = 0; y < pan.screenH; y++) {
        const sy = row + y
        if (sy >= src.height) break
        let i = (sy * src.width) * 4
        let o = y * pan.screenW * 4
        for (let x = 0; x < w; x++, i += 4, o += 4) {
          // a colour word of 0 is not drawn: the screen's black shows through
          const on = from[i + 3] !== 0
          to[o] = on ? Math.max(0, from[i] - dark) : 0
          to[o + 1] = on ? Math.max(0, from[i + 1] - dark) : 0
          to[o + 2] = on ? Math.max(0, from[i + 2] - dark) : 0
          to[o + 3] = 255
        }
      }
      g.putImageData(out, 0, 0)
    },
    [src, pan],
  )

  // One clock: the show's own, a frame each 1/hz s, as the game turns it.
  useEffect(() => {
    let raf = 0
    let shown = -1
    const tick = (now: number) => {
      const s = st.current
      if (s.playing) {
        s.t += (now - s.last) / 1000
        if (s.t >= seconds) {
          s.t = seconds
          s.playing = false
          setPlaying(false)
        }
      }
      s.last = now
      const f = s.fresh ? firstLit : Math.min(frames - 1, Math.floor(s.t * pan.hz))
      if (f !== shown) {
        shown = f
        draw(f)
        setFrame(f)
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [draw, frames, firstLit, seconds, pan.hz])

  // The transport paused by hand (its bar) pauses the show; the voice
  // ending by itself does not, the show running on to its last frame.
  useEffect(
    () =>
      transport.subscribe(() => {
        const s = st.current
        if (!s.playing || !holds(s.voice) || transport.state.playing) return
        if (transport.position() < transport.state.duration - 0.25) {
          s.playing = false
          setPlaying(false)
        }
      }),
    [],
  )

  const start = useCallback(
    async (from: number) => {
      const s = st.current
      if (from >= seconds) from = 0
      if (voice && playSong) {
        // its voice, loaded already: from its row in Voices, or by this bromide's
        const l0 = transport.state.loaded
        if (!holds(s.voice) && l0 && isVoice(l0, voice, result.program)) s.voice = l0.resultId
        if (holds(s.voice)) {
          if (from < transport.state.duration) {
            transport.seek(from)
            void transport.play()
          }
        } else {
          setAsking(true)
          try {
            await playSong(voice.ref, voice.title, disc)
          } finally {
            setAsking(false)
          }
          const l = transport.state.loaded
          // asked and told no, what played plays on: the show waits
          if (!l || !isVoice(l, voice, result.program)) return
          s.voice = l.resultId
          if (from > 0) transport.seek(from)
        }
      }
      s.t = from
      s.last = performance.now()
      s.fresh = false
      setFresh(false)
      s.playing = true
      setPlaying(true)
    },
    [voice, playSong, disc, seconds, result.program],
  )

  const pause = useCallback(() => {
    const s = st.current
    s.playing = false
    setPlaying(false)
    if (holds(s.voice) && transport.state.playing) transport.pause()
  }, [])

  const toggle = useCallback(() => {
    if (st.current.playing) pause()
    else void start(st.current.fresh ? 0 : st.current.t)
  }, [pause, start])

  useEffect(() => claimSpace(toggle), [toggle])

  const seekTo = (f: number) => {
    const s = st.current
    s.fresh = false
    setFresh(false)
    s.t = f / pan.hz
    if (s.playing && holds(s.voice)) {
      if (s.t < transport.state.duration) {
        transport.seek(s.t)
        if (!transport.state.playing) void transport.play()
      } else if (transport.state.playing) {
        // past the voice's end: ended, not paused by hand, so the show runs on
        transport.seek(transport.state.duration)
        transport.pause()
      }
    }
    draw(f)
    setFrame(f)
  }

  // The show at whole multiples while it fits; the whole picture beside it,
  // as tall as it while there is room, else as wide as the room left.
  const room = (box - PAD - GAP - THUMB) / pan.screenW
  const z = room >= 1 ? Math.floor(room) : Math.max(0.5, room)
  const showW = Math.round(pan.screenW * z)
  const showH = Math.round(pan.screenH * z)
  const thumb = Math.min(showH / pan.h, Math.max(THUMB, box - PAD - GAP - showW) / pan.w)
  const thumbW = Math.round(pan.w * thumb)
  const thumbH = Math.round(pan.h * thumb)
  const row = pan.rows[frame] ?? 0
  const t = fresh ? 0 : frame / pan.hz

  return (
    <div ref={boxRef} className="flex-1 min-w-0 min-h-0 overflow-auto stage-scroll flex flex-col">
      <div className="bg-stage text-stage-foreground">
        <div className="p-4 flex items-start justify-center gap-5">
          <div className="relative shrink-0" style={{ width: showW, height: showH }}>
            <canvas
              ref={canvasRef}
              width={pan.screenW}
              height={pan.screenH}
              className="bg-black shadow-xl pixelated"
              style={{ width: showW, height: showH }}
            />
            {(!src || asking) && (
              <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                <div className="rounded-md bg-black/70 px-3 py-2 text-xs flex items-center gap-2">
                  {failed ? (
                    <span className="text-red-300">The picture could not be read back</span>
                  ) : (
                    <>
                      <LoaderCircle className="w-3.5 h-3.5 animate-spin" /> {asking ? 'Loading its voice…' : 'Reading…'}
                    </>
                  )}
                </div>
              </div>
            )}
          </div>
          <div className="relative shrink-0" style={{ width: thumbW, height: thumbH }} title="The whole picture: the box is what the screen shows">
            <img
              src={blobUrl(pan.blob, 'png')}
              alt=""
              draggable={false}
              className="pixelated bg-black"
              style={{ width: thumbW, height: thumbH }}
            />
            <div
              className="absolute inset-x-0 border-2 pointer-events-none"
              // the page's base rule colours every border; this one is the screen's
              style={{
                top: Math.round(row * thumb),
                height: Math.round(pan.screenH * thumb),
                borderColor: 'var(--color-primary)',
                boxShadow: '0 0 0 1px rgb(0 0 0 / 0.6)',
              }}
            />
          </div>
        </div>
        <div className="h-11 bg-stage-raised border-t border-stage-border flex items-center gap-2 px-3">
          <ToolButton title={playing ? 'Pause (Space)' : voice ? 'Play, with its voice (Space)' : 'Play (Space)'} onClick={toggle}>
            {playing ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
          </ToolButton>
          <ToolButton title="From the start" onClick={() => void start(0)}>
            <RotateCcw className="w-3.5 h-3.5" />
          </ToolButton>
          <span className="text-[11px] font-mono w-28 shrink-0">
            {formatTime(t)} <span className="text-stage-muted">/ {formatTime(seconds)}</span>
          </span>
          <input
            type="range"
            min={0}
            max={frames - 1}
            step={1}
            value={fresh ? 0 : frame}
            onChange={(e) => seekTo(Number(e.target.value))}
            className="flex-1 min-w-16 accent-primary cursor-pointer"
            title="Seek"
          />
          {advanced && (
            <span className="text-[11px] font-mono text-stage-muted shrink-0" title="The frame, and the picture's row the screen begins at">
              frame {frame} · row {row}
            </span>
          )}
          <ToolButton title="Export the whole picture as PNG" wide onClick={() => onExport(0, false)}>
            <Download className="w-3.5 h-3.5" /> <span className="text-[11px]">PNG</span>
          </ToolButton>
        </div>
      </div>
      {page && <Page key={advanced ? 'advanced' : 'fan'} result={result} advanced={advanced} disc={disc} />}
    </div>
  )
}

/** What the bromide is, in plain words first: its card, laid out as a page. */
const Page = memo(function Page({ result, advanced, disc }: { result: Result; advanced: boolean; disc: string }) {
  const page = result.page!
  const [open, setOpen] = useState(advanced)
  return (
    <div className="p-4 flex justify-center bg-background">
      <div className="w-full max-w-3xl rounded-lg border border-border bg-card shadow-sm p-4 space-y-4 selectable">
        <div>
          <h2 className="text-base font-semibold">{page.title}</h2>
          <p className="text-xs text-secondary-foreground">
            {page.subtitle}
            <span className="font-mono text-muted-foreground">
              {' · '}
              {page.written}
              {advanced && page.hex !== page.written && ` · ${page.hex}`}
            </span>
          </p>
        </div>
        {page.error && <p className="text-[11px] rounded-md bg-warn-soft text-warn px-2 py-1.5">{page.error}</p>}
        {page.facts.length > 0 && (
          <div className="space-y-1">
            {page.facts.map(([k, v], i) => (
              <div key={i} className="grid grid-cols-[120px_1fr] gap-2 text-xs">
                <span className="text-muted-foreground">{k}</span>
                <span className="break-words min-w-0">{v}</span>
              </div>
            ))}
          </div>
        )}
        {page.note &&
          page.note.split(/\n\s*\n/).map((p, i) => (
            <p key={i} className="text-xs leading-relaxed text-secondary-foreground whitespace-pre-line">
              {p}
            </p>
          ))}
        {page.groups.length > 0 && <LinkGroups groups={page.groups} disc={disc} hex={advanced} />}
        <div className="border-t border-border pt-3">
          <button
            className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground hover:text-foreground cursor-pointer"
            onClick={() => setOpen((o) => !o)}
          >
            {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
            Extended info
          </button>
          {open && (
            <div className="mt-2 space-y-1">
              {page.extended.map(([k, v], i) => (
                <div key={i} className="grid grid-cols-[120px_1fr] gap-2 text-[11px]">
                  <span className="text-muted-foreground">{k}</span>
                  <span className="font-mono break-words min-w-0">{v}</span>
                </div>
              ))}
              {page.proven.length > 0 && (
                <div className="grid grid-cols-[120px_1fr] gap-2 text-[11px]">
                  <span className="text-muted-foreground">Proven by</span>
                  <span className="font-mono break-words min-w-0">{page.proven.join(', ')}</span>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
})
