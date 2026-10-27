import { useEffect } from 'react'
import type { Waveform } from '../../lib/api'
import { transport } from '../../lib/transport'
import { useCanvas } from '../../lib/useCanvas'
import { formatTime } from '../../lib/utils'

const H = 200

function niceStep(seconds: number, width: number): number {
  const target = (seconds / width) * 90 // a label every ~90 px
  for (const s of [0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120]) if (s >= target) return s
  return 300
}

/**
 * A sample's (or a score's) shape: min/max per column, computed by the
 * backend from the decoded PCM. The loop point is the one piece of ADPCM
 * metadata that changes how a sample is meant to be heard, so it is drawn;
 * a score's endless loop is drawn the same way, from its start to its end.
 * A score's columns come in as the backend plays its map in the background
 * (`columns` of them in all): drawn from the left as they arrive.
 * Click to play from a point.
 */
export function WaveformView({
  waveform,
  active,
  onSeek,
}: {
  waveform: Waveform
  /** This result's clip is the one in the transport. */
  active: boolean
  onSeek: (seconds: number) => void
}) {
  const { lo, hi, seconds, loop } = waveform
  const loopEnd = waveform.loopEnd ?? 1
  const { ref, invalidate } = useCanvas((ctx, w, h) => {
    ctx.fillStyle = '#1b1a19'
    ctx.fillRect(0, 0, w, h)
    const mid = (h - 18) / 2
    const scale = (mid - 6) / 32768
    if (loop !== null) {
      ctx.fillStyle = 'rgba(234, 179, 8, 0.07)'
      ctx.fillRect(loop * w, 0, (loopEnd - loop) * w, h - 18)
    }
    ctx.strokeStyle = 'rgba(255,255,255,0.08)'
    ctx.beginPath()
    ctx.moveTo(0, mid + 0.5)
    ctx.lineTo(w, mid + 0.5)
    ctx.stroke()

    const n = waveform.columns ?? lo.length
    if (lo.length) {
      ctx.fillStyle = '#e05a2b'
      for (let x = 0; x < w; x++) {
        const a = Math.floor((x / w) * n)
        const b = Math.max(a + 1, Math.floor(((x + 1) / w) * n))
        if (a >= lo.length) break
        let mn = 0
        let mx = 0
        for (let i = a; i < b && i < lo.length; i++) {
          if (lo[i] < mn) mn = lo[i]
          if (hi[i] > mx) mx = hi[i]
        }
        const y0 = mid - mx * scale
        const y1 = mid - mn * scale
        ctx.fillRect(x, y0, 1, Math.max(1, y1 - y0))
      }
    }
    if (loop !== null) {
      const x = Math.round(loop * w) + 0.5
      ctx.strokeStyle = '#eab308'
      ctx.beginPath()
      ctx.moveTo(x, 0)
      ctx.lineTo(x, h - 18)
      if (loopEnd < 1) {
        const xe = Math.round(loopEnd * w) + 0.5
        ctx.moveTo(xe, 0)
        ctx.lineTo(xe, h - 18)
      }
      ctx.stroke()
      ctx.fillStyle = '#eab308'
      ctx.font = '10px ui-monospace, monospace'
      ctx.fillText('loop', Math.min(x + 4, w - 28), 12)
    }

    // time axis
    ctx.fillStyle = '#262422'
    ctx.fillRect(0, h - 18, w, 18)
    ctx.fillStyle = '#8a7f73'
    ctx.font = '10px ui-monospace, monospace'
    const step = niceStep(seconds, w)
    for (let t = 0; t <= seconds + 1e-9; t += step) {
      const x = Math.round((t / seconds) * w) + 0.5
      ctx.fillRect(x, h - 18, 1, 4)
      const label = seconds < 2 ? `${(t * 1000).toFixed(0)}ms` : step < 1 ? `${t.toFixed(1)}s` : formatTime(t).replace(/\.\d$/, '')
      if (x < w - 30) ctx.fillText(label, x + 3, h - 5)
    }

    if (active && seconds > 0) {
      const p = transport.position()
      if (p > 0 || transport.state.playing) {
        const x = Math.round(Math.min(1, p / seconds) * w) + 0.5
        ctx.strokeStyle = '#ffffff'
        ctx.lineWidth = 1.5
        ctx.beginPath()
        ctx.moveTo(x, 0)
        ctx.lineTo(x, h - 18)
        ctx.stroke()
        ctx.lineWidth = 1
      }
    }
  })

  useEffect(() => invalidate(), [waveform, active, invalidate])

  // While this clip plays, redraw every frame for the playhead.
  useEffect(() => {
    if (!active) return
    let raf = 0
    const tick = () => {
      invalidate()
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [active, invalidate])

  return (
    <div className="rounded-lg overflow-hidden border border-stage-border shadow-sm">
      <canvas
        ref={ref}
        className="block w-full cursor-crosshair"
        style={{ height: H }}
        onClick={(e) => {
          const r = e.currentTarget.getBoundingClientRect()
          onSeek(((e.clientX - r.left) / r.width) * seconds)
        }}
        title="Click to play from here"
      />
      {waveform.note && <div className="px-3 py-1 text-[10px] font-mono text-stage-muted bg-stage-raised">{waveform.note}</div>}
    </div>
  )
}
