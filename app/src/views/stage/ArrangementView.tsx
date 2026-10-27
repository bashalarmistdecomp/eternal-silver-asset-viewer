import { ZoomIn, ZoomOut } from 'lucide-react'
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { ArrangementData } from '../../lib/api'
import { channelColor } from '../../lib/colors'
import { transport } from '../../lib/transport'
import { useCanvas } from '../../lib/useCanvas'
import { clamp, cn } from '../../lib/utils'

const LABELS = 132
const RULER = 22
const LANE = 38
const PAD = 3

/** seconds <-> ticks through the sequence's own tempo map. */
function timeMap(data: ArrangementData) {
  const marks = data.tempo.length ? data.tempo : [[0, 0] as [number, number]]
  const toTick = (s: number) => {
    if (s <= marks[0][0]) return marks[0][1]
    for (let i = 0; i < marks.length - 1; i++) {
      const [s0, t0] = marks[i]
      const [s1, t1] = marks[i + 1]
      if (s <= s1) return s1 > s0 ? t0 + ((t1 - t0) * (s - s0)) / (s1 - s0) : t0
    }
    return marks[marks.length - 1][1]
  }
  const toSec = (t: number) => {
    if (t <= marks[0][1]) return marks[0][0]
    for (let i = 0; i < marks.length - 1; i++) {
      const [s0, t0] = marks[i]
      const [s1, t1] = marks[i + 1]
      if (t <= t1) return t1 > t0 ? s0 + ((s1 - s0) * (t - t0)) / (t1 - t0) : s0
    }
    return marks[marks.length - 1][0]
  }
  return { toTick, toSec }
}

/** [start, end] ticks of each loop: where the time map jumps back. */
function loopsOf(data: ArrangementData): [number, number][] {
  const out: [number, number][] = []
  for (let i = 1; i < data.tempo.length; i++) {
    const [s0, t0] = data.tempo[i - 1]
    const [s1, t1] = data.tempo[i]
    if (s1 === s0 && t1 < t0 && !out.some(([a, b]) => a === t1 && b === t0)) out.push([t1, t0])
  }
  return out
}

/**
 * A sequence as a sequencer's arrangement page shows it: one lane per MIDI
 * channel, notes as bars on one bar-numbered ruler, pitch placed within the
 * lane. The data is the SEQ's own note spans and tempo map, so the
 * playhead follows tempo changes.
 */
export function ArrangementView({ data, active, onSeek }: { data: ArrangementData; active: boolean; onSeek: (seconds: number) => void }) {
  const scroller = useRef<HTMLDivElement>(null)
  const [view, setView] = useState({ left: 0, width: 800 })
  const beats = Math.max(1, data.ticks / Math.max(1, data.resolution))
  const [ppb, setPpb] = useState<number | null>(null) // null = fit
  const fitPpb = clamp((view.width - LABELS - 24) / beats, 1.5, 60)
  const px = ppb ?? fitPpb
  const contentW = LABELS + beats * px + 24
  const height = RULER + data.lanes.length * LANE
  const map = useMemo(() => timeMap(data), [data])
  const loops = useMemo(() => loopsOf(data), [data])
  const ranges = useMemo(
    () =>
      data.lanes.map((l) => {
        let lo = 127
        let hi = 0
        for (const n of l.notes) {
          lo = Math.min(lo, n[2])
          hi = Math.max(hi, n[2])
        }
        return { lo, span: Math.max(1, hi - lo) }
      }),
    [data],
  )

  const { ref, invalidate } = useCanvas((ctx, w) => {
    const left = view.left
    const xOf = (tick: number) => LABELS + (tick / data.resolution) * px - left
    ctx.fillStyle = '#ffffff'
    ctx.fillRect(0, 0, w, height)

    // lanes
    data.lanes.forEach((_lane, row) => {
      const top = RULER + row * LANE
      ctx.fillStyle = row % 2 ? '#faf7f4' : '#ffffff'
      ctx.fillRect(LABELS, top, w - LABELS, LANE)
      ctx.fillStyle = '#ebe5de'
      ctx.fillRect(LABELS, top + LANE - 1, w - LABELS, 1)
    })

    // bar lines
    const barPx = data.beatsPerBar * px
    const labelEvery = barPx >= 40 ? 1 : barPx >= 20 ? 2 : barPx >= 10 ? 4 : 8
    const firstBar = Math.max(0, Math.floor((left - 0) / barPx))
    for (let b = firstBar; ; b++) {
      const x = Math.round(LABELS + b * barPx - left) + 0.5
      if (x > w) break
      if (x < LABELS) continue
      ctx.fillStyle = b % 4 === 0 ? '#d9d0c7' : '#ebe5de'
      ctx.fillRect(x, RULER, 1, height - RULER)
    }

    // notes
    data.lanes.forEach((lane, row) => {
      const top = RULER + row * LANE
      const { lo, span } = ranges[row]
      const usable = LANE - PAD * 2 - 4
      const nh = clamp(Math.floor(usable / Math.max(1, span / 2)), 2, 5)
      const colour = channelColor(lane.channel)
      ctx.fillStyle = colour
      for (const [tick, dur, note, vel] of lane.notes) {
        const x = xOf(tick)
        const nw = Math.max(1.5, (dur / data.resolution) * px)
        if (x + nw < LABELS || x > w) continue
        const y = top + LANE - PAD - nh - ((note - lo) / span) * usable
        ctx.globalAlpha = 0.45 + (vel / 127) * 0.55
        ctx.fillRect(Math.max(LABELS, x), y, nw - Math.max(0, LABELS - x), nh)
      }
      ctx.globalAlpha = 1
    })

    // ruler
    ctx.fillStyle = '#f0ebe5'
    ctx.fillRect(LABELS, 0, w - LABELS, RULER)
    ctx.fillStyle = '#d9d0c7'
    ctx.fillRect(0, RULER - 1, w, 1)
    ctx.font = '10px ui-monospace, monospace'
    for (let b = firstBar; ; b++) {
      const x = Math.round(LABELS + b * barPx - left) + 0.5
      if (x > w) break
      if (x < LABELS) continue
      const tall = b % labelEvery === 0
      ctx.fillStyle = tall ? '#8a7f73' : '#c4b9ad'
      ctx.fillRect(x, tall ? 4 : 12, 1, RULER - (tall ? 5 : 13))
      if (tall) {
        ctx.fillStyle = '#5c534a'
        ctx.fillText(String(b + 1), x + 3, 13)
      }
    }
    // loops, as the score's NRPN marks set them
    for (const [start, end] of loops) {
      const x0 = Math.max(LABELS, xOf(start))
      const x1 = Math.min(w, xOf(end))
      if (x1 <= x0) continue
      ctx.fillStyle = '#eab308'
      ctx.fillRect(x0, RULER - 4, x1 - x0, 3)
      if (xOf(start) >= LABELS) ctx.fillRect(Math.round(xOf(start)), 2, 1, RULER - 3)
      if (xOf(end) <= w) ctx.fillRect(Math.round(xOf(end)), 2, 1, RULER - 3)
    }

    // labels column
    ctx.fillStyle = '#ffffff'
    ctx.fillRect(0, 0, LABELS, height)
    ctx.fillStyle = '#f0ebe5'
    ctx.fillRect(0, 0, LABELS, RULER)
    ctx.fillStyle = '#8a7f73'
    ctx.fillText(`${data.lanes.reduce((n, l) => n + l.notes.length, 0).toLocaleString()} notes`, 10, 14)
    data.lanes.forEach((lane, row) => {
      const top = RULER + row * LANE
      ctx.fillStyle = row % 2 ? '#faf7f4' : '#ffffff'
      ctx.fillRect(0, top, LABELS, LANE)
      ctx.fillStyle = channelColor(lane.channel)
      ctx.fillRect(6, top + 6, 4, LANE - 12)
      ctx.fillStyle = '#2c2520'
      ctx.font = '600 11px system-ui, sans-serif'
      ctx.fillText(`ch ${lane.channel}`, 16, top + 16)
      ctx.fillStyle = '#8a7f73'
      ctx.font = '10px ui-monospace, monospace'
      ctx.fillText((lane.label || `${lane.notes.length} notes`).slice(0, 18), 16, top + 29)
      ctx.fillStyle = '#ebe5de'
      ctx.fillRect(0, top + LANE - 1, LABELS, 1)
    })
    ctx.fillStyle = '#d9d0c7'
    ctx.fillRect(LABELS - 1, 0, 1, height)

    // playhead
    if (active) {
      const p = transport.position()
      if (p > 0 || transport.state.playing) {
        const x = Math.round(xOf(map.toTick(p))) + 0.5
        if (x >= LABELS && x <= w) {
          ctx.fillStyle = '#e05a2b'
          ctx.fillRect(x - 0.5, 0, 2, height)
          ctx.beginPath()
          ctx.moveTo(x - 5, 0)
          ctx.lineTo(x + 6, 0)
          ctx.lineTo(x + 0.5, 7)
          ctx.fill()
        }
      }
    }
  })

  useLayoutEffect(() => {
    const el = scroller.current
    if (!el) return
    const update = () => setView({ left: el.scrollLeft, width: el.clientWidth })
    update()
    const ro = new ResizeObserver(update)
    ro.observe(el)
    el.addEventListener('scroll', update, { passive: true })
    return () => {
      ro.disconnect()
      el.removeEventListener('scroll', update)
    }
  }, [])

  useEffect(() => invalidate(), [view, px, data, active, invalidate])

  // While this sequence plays: redraw for the playhead, and turn the page
  // when it reaches the edge (never fighting a scroll the user made).
  useEffect(() => {
    if (!active) return
    let raf = 0
    const tick = () => {
      const el = scroller.current
      if (el && transport.state.playing) {
        const x = LABELS + (map.toTick(transport.position()) / data.resolution) * px
        const visible = el.clientWidth - LABELS
        if (x < el.scrollLeft + LABELS || x > el.scrollLeft + el.clientWidth - 24) {
          el.scrollLeft = Math.max(0, x - LABELS - visible * 0.1)
        }
      }
      invalidate()
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [active, invalidate, map, px, data.resolution])

  const zoomBy = (f: number) => setPpb(clamp(px * f, 1.5, 120))

  return (
    <div className="rounded-lg border border-border bg-card shadow-sm overflow-hidden">
      <div className="h-8 px-2 border-b border-border flex items-center gap-1 text-[11px] text-muted-foreground">
        <span className="font-mono">
          {data.lanes.length} channels · {Math.max(1, Math.ceil(beats / data.beatsPerBar))} bars · {data.resolution} ticks/quarter
        </span>
        <div className="flex-1" />
        <button className="w-6 h-6 rounded hover:bg-muted flex items-center justify-center cursor-pointer" title="Zoom out" onClick={() => zoomBy(1 / 1.5)}>
          <ZoomOut className="w-3.5 h-3.5" />
        </button>
        <button
          className={cn('h-6 px-1.5 rounded font-mono cursor-pointer', ppb === null ? 'bg-accent text-primary' : 'hover:bg-muted')}
          title="Fit the whole sequence"
          onClick={() => setPpb(null)}
        >
          fit
        </button>
        <button className="w-6 h-6 rounded hover:bg-muted flex items-center justify-center cursor-pointer" title="Zoom in" onClick={() => zoomBy(1.5)}>
          <ZoomIn className="w-3.5 h-3.5" />
        </button>
      </div>
      <div ref={scroller} className="overflow-x-auto overflow-y-hidden" style={{ height: height + 10 }}>
        <div style={{ width: contentW, height, position: 'relative' }}>
          <canvas
            ref={ref}
            className="cursor-crosshair"
            style={{ position: 'sticky', left: 0, top: 0, width: view.width, height, display: 'block' }}
            onClick={(e) => {
              const r = e.currentTarget.getBoundingClientRect()
              const x = e.clientX - r.left
              if (x < LABELS) return
              const tick = ((x - LABELS + view.left) / px) * data.resolution
              onSeek(map.toSec(tick))
            }}
            title="Click to play from here"
          />
        </div>
      </div>
    </div>
  )
}
