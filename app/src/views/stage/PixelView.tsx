import { Download, Grid3x3, Maximize2, Pause, Play, ZoomIn, ZoomOut } from 'lucide-react'
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { blobUrl } from '../../lib/backend'
import type { Layer } from '../../lib/api'
import { useStored } from '../../lib/hooks'
import { cn } from '../../lib/utils'
import { ToolGroup, Toolbar } from './Toolbar'

const ZOOMS = [0.125, 0.25, 0.5, 1, 2, 3, 4, 6, 8, 12, 16]
/** Fit never blows a tiny sprite up past this; zoom in by hand for more. */
const FIT_MAX = 8
const PAD = 24

type Zoom = { fit: true } | { fit: false; z: number }
type Backdrop = 'black' | 'checker'

export interface Picture {
  /** One image per layer, or one per frame of an animation. */
  layers: Layer[]
  animate?: { intervalMs: number }
  /** Draw this instead of a layer (a live scene); zoom, pan and backdrop stay
   *  PixelView's. `layers` then only feed Export. `key` names the selection.
   *  `origin`: the picture pixel at the box's top left, for a picture shown
   *  cut to part of itself; clicks, focus and the readout stay in picture
   *  pixels, and `render` draws the whole picture, shifted. */
  custom?: { key: string; w: number; h: number; origin?: { x: number; y: number }; render: (z: number) => ReactNode }
}

/**
 * Pixels shown as pixels: nearest-neighbour at every zoom of 1x and up,
 * on black. Most results arrive already
 * flattened onto black (viewer_server/present.py); the checkerboard is for
 * the raw layers that keep their alpha (sprite pages), to see where it is.
 *
 * Wheel zooms around the pointer; drag pans.
 */
export function PixelView({
  picture,
  grid: gridAllowed,
  onExport,
  toolbarStart,
  toolbarEnd,
  side,
  onPixelClick,
  focus,
  memory,
}: {
  picture: Picture
  grid: boolean
  onExport?: (layer: number, all: boolean) => void
  /** Before the view's own tools: ToolGroups (a scene's playback). */
  toolbarStart?: ReactNode
  /** After the view's own tools (a map's Export). */
  toolbarEnd?: ReactNode
  /** Beside the picture, under the toolbar (a map's panel). */
  side?: ReactNode
  /** A click (not a drag) on the picture, in picture pixels. */
  onPixelClick?: (x: number, y: number) => void
  /** Scroll this picture pixel to the middle of the view; a new `n` asks again. */
  focus?: { x: number; y: number; n: number }
  /** Remember the zoom under this key (the tab): a 6x sprite zoom must not blow up the next world map. */
  memory: string
}) {
  const [layer, setLayer] = useState(0)
  const [zoom, setZoom] = useStored<Zoom>(`pixel.zoom.${memory}`, { fit: true })
  const [grid, setGrid] = useStored('pixel.grid', false)
  const [backdrop, setBackdrop] = useStored<Backdrop>('pixel.backdrop2', 'black')
  const [box, setBox] = useState({ w: 800, h: 600 })
  const [hover, setHover] = useState<{ x: number; y: number } | null>(null)
  const [playing, setPlaying] = useState(true)
  const [frame, setFrame] = useState(0)
  const scrollRef = useRef<HTMLDivElement>(null)
  const anchor = useRef<{ px: number; py: number; sx: number; sy: number } | null>(null)
  const wheel = useRef(0)
  const drag = useRef<{ x: number; y: number; left: number; top: number } | null>(null)
  const boxRef = useRef<HTMLDivElement>(null)

  const custom = picture.custom
  const animated = !custom && !!picture.animate
  const layers = picture.layers
  const index = animated ? frame % Math.max(1, layers.length) : Math.max(0, Math.min(layer, layers.length - 1))
  const shown: Layer | undefined = layers[index] ?? layers[0]
  const w = custom ? custom.w : animated ? Math.max(...layers.map((l) => l.w)) : (shown?.w ?? 1)
  const h = custom ? custom.h : animated ? Math.max(...layers.map((l) => l.h)) : (shown?.h ?? 1)
  const ox = custom?.origin?.x ?? 0
  const oy = custom?.origin?.y ?? 0

  // A new selection starts on its first layer/frame.
  const ident = custom ? custom.key : layers.map((l) => l.blob).join(',')
  useEffect(() => {
    setLayer(0)
    setFrame(0)
    setPlaying(true)
  }, [ident])

  // Every frame is fetched up front so the animation does not flicker.
  useEffect(() => {
    if (!animated) return
    for (const l of layers) {
      const img = new window.Image()
      img.src = blobUrl(l.blob, 'png')
    }
  }, [animated, layers])

  useEffect(() => {
    if (!animated || !playing || layers.length < 2) return
    const id = setInterval(() => setFrame((f) => (f + 1) % layers.length), picture.animate!.intervalMs)
    return () => clearInterval(id)
  }, [animated, playing, layers.length, picture.animate])

  useLayoutEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const ro = new ResizeObserver(() => setBox({ w: el.clientWidth, h: el.clientHeight }))
    ro.observe(el)
    setBox({ w: el.clientWidth, h: el.clientHeight })
    return () => ro.disconnect()
  }, [])

  const fitZoom = useMemo(() => {
    const avail = Math.min((box.w - PAD * 2) / w, (box.h - PAD * 2) / h)
    if (avail >= 1) return Math.min(FIT_MAX, Math.max(1, Math.floor(avail)))
    return Math.max(ZOOMS[0], avail)
  }, [box, w, h])
  const z = zoom.fit ? fitZoom : zoom.z

  const step = useCallback(
    (dir: 1 | -1, at?: { sx: number; sy: number }) => {
      const el = scrollRef.current
      const next = dir > 0 ? (ZOOMS.find((v) => v > z + 1e-6) ?? z) : ([...ZOOMS].reverse().find((v) => v < z - 1e-6) ?? z)
      if (next === z || !el) return
      // Keep the image pixel under the pointer (or the view's centre) where it is.
      const sx = at?.sx ?? el.clientWidth / 2
      const sy = at?.sy ?? el.clientHeight / 2
      const content = el.firstElementChild as HTMLElement
      const img = content.firstElementChild as HTMLElement
      const ox = img.offsetLeft
      const oy = img.offsetTop
      anchor.current = { px: (el.scrollLeft + sx - ox) / z, py: (el.scrollTop + sy - oy) / z, sx, sy }
      setZoom({ fit: false, z: next })
    },
    [z, setZoom],
  )

  useLayoutEffect(() => {
    const el = scrollRef.current
    const a = anchor.current
    if (!el || !a) return
    anchor.current = null
    const img = (el.firstElementChild as HTMLElement).firstElementChild as HTMLElement
    el.scrollLeft = img.offsetLeft + a.px * z - a.sx
    el.scrollTop = img.offsetTop + a.py * z - a.sy
  }, [z])

  useEffect(() => {
    const el = scrollRef.current
    const box = boxRef.current
    if (!focus || !el || !box) return
    const r = box.getBoundingClientRect()
    const v = el.getBoundingClientRect()
    el.scrollBy({
      left: r.left + (focus.x - ox) * z - (v.left + el.clientWidth / 2),
      top: r.top + (focus.y - oy) * z - (v.top + el.clientHeight / 2),
      behavior: 'smooth',
    })
    // (only a new request scrolls; a zoom keeps the view where it is)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus?.n])

  // Keyboard zoom, from the app-level shortcut handler.
  useEffect(() => {
    const onZoom = (e: Event) => {
      const d = (e as CustomEvent<string>).detail
      if (d === 'in') step(1)
      else if (d === 'out') step(-1)
      else if (d === 'fit') setZoom({ fit: true })
      else if (d === '1') setZoom({ fit: false, z: 1 })
      else if (d === 'grid' && gridAllowed) setGrid((g) => !g)
    }
    window.addEventListener('viewer:zoom', onZoom)
    return () => window.removeEventListener('viewer:zoom', onZoom)
  }, [step, setZoom, setGrid, gridAllowed])

  // One zoom step per wheel notch. A trackpad sends a stream of small
  // deltas; summing them to a notch's worth keeps it from racing.
  const onWheel = (e: React.WheelEvent) => {
    const el = scrollRef.current
    if (!el) return
    const px = e.deltaMode === 1 ? e.deltaY * 40 : e.deltaY
    wheel.current += px
    if (Math.abs(wheel.current) < 60) return
    const dir = wheel.current < 0 ? 1 : -1
    wheel.current = 0
    const r = el.getBoundingClientRect()
    step(dir, { sx: e.clientX - r.left, sy: e.clientY - r.top })
  }

  // React's onWheel is passive; the native listener is what can stop the scroll.
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const stop = (e: WheelEvent) => e.preventDefault()
    el.addEventListener('wheel', stop, { passive: false })
    return () => el.removeEventListener('wheel', stop)
  }, [])

  const showGrid = gridAllowed && grid && z >= 1
  const smooth = z < 1

  // The toolbar's right-hand side: zoom and backdrop, then export.
  const zoomAndExport = (
    <>
      <ToolGroup>
        <ToolButton title="Zoom out (−)" onClick={() => step(-1)}>
          <ZoomOut className="w-3.5 h-3.5" />
        </ToolButton>
        <span className="text-[11px] font-mono w-12 text-center" title={zoom.fit ? 'Fitted to the window' : undefined}>
          {z >= 1 ? `${Math.round(z * 100)}%` : `${(z * 100).toFixed(0)}%`}
        </span>
        <ToolButton title="Zoom in (+)" onClick={() => step(1)}>
          <ZoomIn className="w-3.5 h-3.5" />
        </ToolButton>
        <ToolButton title="Fit (0)" active={zoom.fit} onClick={() => setZoom({ fit: true })}>
          <Maximize2 className="w-3.5 h-3.5" />
        </ToolButton>
        <ToolButton title="Actual size (1)" active={!zoom.fit && z === 1} onClick={() => setZoom({ fit: false, z: 1 })}>
          <span className="text-[10px] font-mono font-semibold">1:1</span>
        </ToolButton>
        {gridAllowed && (
          <ToolButton title="16 px grid (G)" active={grid} onClick={() => setGrid(!grid)}>
            <Grid3x3 className="w-3.5 h-3.5" />
          </ToolButton>
        )}
        <ToolButton
          title={backdrop === 'black' ? 'Backdrop: black — click to show transparency as a checkerboard' : 'Backdrop: checkerboard — click for black'}
          active={backdrop === 'checker'}
          onClick={() => setBackdrop(backdrop === 'black' ? 'checker' : 'black')}
        >
          <span
            className={cn(
              'block w-3.5 h-3.5 rounded-sm border border-stage-border',
              backdrop === 'checker' ? 'checker' : 'bg-black',
            )}
          />
        </ToolButton>
      </ToolGroup>
      {onExport && (
        <ToolGroup>
          <ToolButton
            title={custom ? 'Export the still: every actor on its first tick (PNG)' : animated ? 'Export every frame + a strip (PNG)' : 'Export this layer (PNG)'}
            onClick={() => onExport(index, false)}
            wide
          >
            <Download className="w-3.5 h-3.5" />
            <span className="text-[11px]">PNG</span>
          </ToolButton>
          {!animated && !custom && layers.length > 1 && (
            <ToolButton title="Export every layer (PNG)" onClick={() => onExport(index, true)} wide>
              <span className="text-[11px]">all</span>
            </ToolButton>
          )}
        </ToolGroup>
      )}
      {toolbarEnd && <ToolGroup>{toolbarEnd}</ToolGroup>}
    </>
  )

  return (
    <div className="flex-1 min-w-0 min-h-0 flex flex-col bg-stage">
      <Toolbar end={zoomAndExport}>
        {toolbarStart}
        {custom ? null : animated ? (
          <ToolGroup>
            <ToolButton title={playing ? 'Pause' : 'Play'} onClick={() => setPlaying((p) => !p)}>
              {playing ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
            </ToolButton>
            <input
              type="range"
              min={0}
              max={layers.length - 1}
              value={index}
              onChange={(e) => {
                setPlaying(false)
                setFrame(Number(e.target.value))
              }}
              className="w-40 min-w-0 accent-primary"
              title="Frame"
            />
            <span className="text-[11px] font-mono text-stage-muted w-24">
              frame {index + 1}/{layers.length}
            </span>
          </ToolGroup>
        ) : (
          layers.length > 1 && (
            <ToolGroup>
              <LayerPicker layers={layers} value={index} onChange={setLayer} />
            </ToolGroup>
          )
        )}
        <ToolGroup fill>
          <span className="min-w-0 truncate text-[11px] font-mono text-stage-muted">
            {hover ? `px ${hover.x + ox},${hover.y + oy} · tile ${Math.floor((hover.x + ox) / 16)},${Math.floor((hover.y + oy) / 16)}` : ''}
          </span>
          <span className="shrink-0 text-[11px] font-mono text-stage-muted">
            {w}×{h}
          </span>
        </ToolGroup>
      </Toolbar>
      <div className="flex-1 min-h-0 flex">
        <div
          ref={scrollRef}
          className="relative flex-1 min-w-0 min-h-0 overflow-auto stage-scroll cursor-grab active:cursor-grabbing"
          onWheel={onWheel}
          onPointerDown={(e) => {
            const el = scrollRef.current!
            drag.current = { x: e.clientX, y: e.clientY, left: el.scrollLeft, top: el.scrollTop }
            e.currentTarget.setPointerCapture(e.pointerId)
          }}
          onPointerMove={(e) => {
            const d = drag.current
            if (!d || e.buttons !== 1) return
            const el = scrollRef.current!
            el.scrollLeft = d.left - (e.clientX - d.x)
            el.scrollTop = d.top - (e.clientY - d.y)
          }}
          onPointerUp={(e) => {
            const d = drag.current
            drag.current = null
            const box = boxRef.current
            if (!d || !onPixelClick || !box || Math.hypot(e.clientX - d.x, e.clientY - d.y) > 3) return
            const r = box.getBoundingClientRect()
            const x = Math.floor((e.clientX - r.left) / z)
            const y = Math.floor((e.clientY - r.top) / z)
            if (x >= 0 && y >= 0 && x < w && y < h) onPixelClick(x + ox, y + oy)
          }}
        >
          <div className="min-w-full min-h-full w-max flex items-center justify-center" style={{ padding: PAD }}>
            <div
              ref={boxRef}
              className={cn('relative shrink-0 shadow-[0_0_0_1px_rgba(255,255,255,0.06)]', backdrop === 'checker' ? 'checker' : 'bg-black', custom?.origin && 'overflow-hidden')}
              style={{ width: w * z, height: h * z }}
              onPointerMove={(e) => {
                const r = e.currentTarget.getBoundingClientRect()
                const x = Math.floor((e.clientX - r.left) / z)
                const y = Math.floor((e.clientY - r.top) / z)
                setHover(x >= 0 && y >= 0 && x < w && y < h ? { x, y } : null)
              }}
              onPointerLeave={() => setHover(null)}
            >
              {custom
                ? custom.origin
                  ? <div className="absolute" style={{ left: -ox * z, top: -oy * z }}>{custom.render(z)}</div>
                  : custom.render(z)
                : shown && (
                    <img
                      key={shown.blob}
                      src={blobUrl(shown.blob, 'png')}
                      draggable={false}
                      alt={shown.label}
                      className={cn('absolute left-0 top-0 max-w-none', !smooth && 'pixelated')}
                      style={{ width: shown.w * z, height: shown.h * z }}
                    />
                  )}
              {showGrid && (
                <div
                  className="absolute inset-0 pointer-events-none"
                  style={{
                    backgroundImage:
                      'linear-gradient(to right, rgba(255,255,255,0.18) 1px, transparent 1px), linear-gradient(to bottom, rgba(255,255,255,0.18) 1px, transparent 1px)',
                    backgroundSize: `${16 * z}px ${16 * z}px`,
                  }}
                />
              )}
            </div>
          </div>
        </div>
        {side}
      </div>
    </div>
  )
}

function LayerPicker({ layers, value, onChange }: { layers: Layer[]; value: number; onChange: (i: number) => void }) {
  const short = layers.length <= 6 && layers.every((l) => l.label.length <= 12)
  if (short)
    return (
      <div className="min-w-0 flex flex-wrap gap-1">
        {layers.map((l, i) => (
          <button
            key={i}
            onClick={() => onChange(i)}
            className={cn(
              'h-6 px-2 rounded text-[11px] font-medium border cursor-pointer transition-colors',
              i === value ? 'bg-primary text-primary-foreground border-primary' : 'bg-stage border-stage-border text-stage-muted hover:text-stage-foreground',
            )}
          >
            {l.label}
          </button>
        ))}
      </div>
    )
  return (
    <select
      value={value}
      onChange={(e) => onChange(Number(e.target.value))}
      className="h-6 min-w-0 max-w-72 rounded border border-stage-border bg-stage px-1.5 text-[11px] text-stage-foreground cursor-pointer"
      title="Layer"
    >
      {layers.map((l, i) => (
        <option key={i} value={i}>
          {l.label}
        </option>
      ))}
    </select>
  )
}

export function ToolButton({
  title,
  active,
  wide,
  onClick,
  children,
}: {
  title: string
  active?: boolean
  wide?: boolean
  onClick: () => void
  children: ReactNode
}) {
  return (
    <button
      title={title}
      onClick={onClick}
      className={cn(
        'h-7 rounded flex items-center justify-center gap-1 cursor-pointer transition-colors shrink-0',
        wide ? 'px-2' : 'w-7',
        active ? 'bg-primary/20 text-primary' : 'text-stage-foreground/80 hover:bg-white/10 hover:text-white',
      )}
    >
      {children}
    </button>
  )
}
