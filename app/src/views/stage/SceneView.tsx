import { ActorAnim, type AnimDef } from '../../lib/game/actorAnim'
import { Crosshair, Pause, Play, RotateCcw, StepForward, Tag } from 'lucide-react'
import { useCallback, useEffect, useMemo, useReducer, useRef, useState, type ReactNode } from 'react'
import type { Layer, Scene, SceneActor, SceneSheet } from '../../lib/api'
import { useLive, useStored } from '../../lib/hooks'
import { loadImage as load, pixels } from '../../lib/sceneImages'
import { cn } from '../../lib/utils'
import { PixelView, ToolButton } from './PixelView'
import { ToolGroup } from './Toolbar'

const SPEEDS = [0.25, 0.5, 1, 2]
/** A long stall (a hidden window) must not replay minutes of ticks at once. */
const MAX_TICKS_PER_FRAME = 32

interface Loaded {
  bg: HTMLImageElement | null
  sheets: HTMLImageElement[]
  /** Each sheet's pixels, for clicking an actor by its ink rather than its box. */
  alpha: (ImageData | null)[]
}

/** The cell box an actor's sheet covers, in scene pixels. */
function cellBox(a: SceneActor, sh: SceneSheet) {
  const left = a.mirror ? a.x - sh.cellW + sh.anchorX : a.x - sh.anchorX
  return { left, top: a.y - sh.anchorY, w: sh.cellW, h: sh.cellH }
}

/**
 * Actors played the way the engine plays them: each one ticks its block's
 * own anim table (lib/game/actorAnim.ts) once per frame at the scene's
 * tick rate, and draws that step's cell from its pose sheet, mirrored about
 * the anchor when the code mirrors it. The backend sends sheets and tables,
 * never frames (backend/viewer_tabs/scene.py).
 */
export function SceneView({
  scene,
  stills,
  onExport,
  memory,
  actions,
  advanced = false,
}: {
  scene: Scene
  /** Server-rendered stills: what Export writes. */
  stills: Layer[]
  onExport?: (layer: number, all: boolean) => void
  memory: string
  /** After the scene's own tools: a fight's music buttons. */
  actions?: ReactNode
  /** Advanced mode: an anim is named as the census names it (the status
   *  bits the code tests), and the strip cites what plays it and the clock. */
  advanced?: boolean
}) {
  const ident = useMemo(
    () => `${scene.background ?? ''}|${scene.sheets.map((s) => s.blob).join(',')}|${scene.actors.length}`,
    [scene],
  )
  const [loaded, setLoaded] = useState<Loaded | null>(null)
  const [failed, setFailed] = useState(false)
  const [playing, setPlaying] = useState(true)
  const [speed, setSpeed] = useStored('scene.speed', 1)
  const [anchors, setAnchors] = useStored('scene.anchors', false)
  const [labels, setLabels] = useState(scene.labels)
  const [sel, setSel] = useState(0)
  const [, bump] = useReducer((n: number) => n + 1, 0)
  const canvas = useRef<HTMLCanvasElement | null>(null)
  const ticks = useRef(0)
  const live = useRef({ playing, speed })
  useEffect(() => {
    live.current = { playing, speed }
  }, [playing, speed])

  // One engine per actor, started on the anim the scene names (battle entry
  // plays anim 0 for every enemy — BtlEnemyLoad (0x8002B3AC)).
  const engines = useMemo(
    () =>
      scene.actors.map((a) => {
        const e = new ActorAnim(scene.sheets[a.sheet].anims)
        e.play(a.anim)
        return e
      }),
    [scene],
  )
  // Battle depth, back to front: lower on screen draws in front, and at equal
  // y the lower slot (listed first) does — sprite_draw (0x8001A528) links each
  // packet with AddPrim (0x8008E9D8) at the head of its OT entry, slots in
  // order, so the first slot drawn is painted last. As scene.draw_order.
  const order = useMemo(() => {
    const idx = scene.actors.map((_, i) => i)
    return scene.depth === 'y' ? idx.sort((i, j) => scene.actors[i].y - scene.actors[j].y || j - i) : idx
  }, [scene])

  // (Stage keys this view by result, so a new selection starts fresh.)
  useEffect(() => {
    let alive = true
    Promise.all([scene.background ? load(scene.background) : Promise.resolve(null), Promise.all(scene.sheets.map((s) => load(s.blob)))])
      .then(([bg, sheets]) => {
        if (alive) setLoaded({ bg, sheets, alpha: sheets.map(pixels) })
      })
      .catch(() => alive && setFailed(true))
    return () => {
      alive = false
    }
  }, [scene.background, scene.sheets])

  const draw = useCallback(() => {
    const c = canvas.current
    if (!c || !loaded) return
    const g = c.getContext('2d')!
    g.imageSmoothingEnabled = false
    g.clearRect(0, 0, c.width, c.height)
    if (loaded.bg) g.drawImage(loaded.bg, 0, 0)
    for (const i of order) {
      const a = scene.actors[i]
      const sh = scene.sheets[a.sheet]
      const pose = engines[i].pose
      if (pose < 0 || pose >= sh.poses) continue
      const sx = (pose % sh.columns) * sh.cellW
      const sy = Math.floor(pose / sh.columns) * sh.cellH
      const img = loaded.sheets[a.sheet]
      if (a.mirror) {
        // Engine column c -> 2X-1-c: flip about the anchor column's left edge.
        g.save()
        g.translate(a.x, 0)
        g.scale(-1, 1)
        g.drawImage(img, sx, sy, sh.cellW, sh.cellH, -sh.anchorX, a.y - sh.anchorY, sh.cellW, sh.cellH)
        g.restore()
      } else {
        g.drawImage(img, sx, sy, sh.cellW, sh.cellH, a.x - sh.anchorX, a.y - sh.anchorY, sh.cellW, sh.cellH)
      }
    }
  }, [loaded, order, scene, engines])

  // The frame loop: whole ticks at the scene's rate, scaled by the speed.
  useEffect(() => {
    if (!loaded) return
    const tickMs = 1000 / scene.tickHz
    let raf = 0
    let last = performance.now()
    let acc = 0
    const frame = (now: number) => {
      const dt = now - last
      last = now
      if (live.current.playing) {
        acc += dt * live.current.speed
        let n = 0
        while (acc >= tickMs && n < MAX_TICKS_PER_FRAME) {
          for (const e of engines) e.tick()
          ticks.current++
          acc -= tickMs
          n++
        }
        if (n === MAX_TICKS_PER_FRAME) acc = 0
      }
      draw()
      raf = requestAnimationFrame(frame)
    }
    raf = requestAnimationFrame(frame)
    return () => cancelAnimationFrame(raf)
  }, [loaded, draw, engines, scene.tickHz])

  const stepOnce = () => {
    setPlaying(false)
    for (const e of engines) e.tick()
    ticks.current++
  }
  const restart = () => {
    for (const e of engines) e.replay(e.anim)
    ticks.current = 0
  }
  const playOn = (i: number, id: number) => {
    engines[i]?.replay(id)
    bump()
  }
  const playAll = (id: number) => {
    for (const e of engines) e.replay(id)
    bump()
  }

  // An anim every actor's table can play, for the "all" picker.
  const common = useMemo(() => {
    if (scene.actors.length < 2) return []
    const first = scene.sheets[scene.actors[0].sheet].anims
    return first
      .filter((d) => scene.actors.every((a) => scene.sheets[a.sheet].anims[d.index]?.steps.length))
      .map((d) => ({ id: d.index, name: animName(d, advanced) }))
  }, [scene, advanced])

  // Pick an actor by its ink, topmost first; else the nearest anchor.
  const pick = (x: number, y: number) => {
    if (!loaded) return
    for (const i of [...order].reverse()) {
      const a = scene.actors[i]
      const sh = scene.sheets[a.sheet]
      const b = cellBox(a, sh)
      if (x < b.left || y < b.top || x >= b.left + b.w || y >= b.top + b.h) continue
      const cx = a.mirror ? b.w - 1 - (x - b.left) : x - b.left
      const pose = engines[i].pose
      const px = (pose % sh.columns) * sh.cellW + cx
      const py = Math.floor(pose / sh.columns) * sh.cellH + (y - b.top)
      const data = loaded.alpha[a.sheet]
      if (data && px < data.width && py < data.height && data.data[(py * data.width + px) * 4 + 3] > 0) return setSel(i)
    }
    let best = -1
    let dist = 24
    scene.actors.forEach((a, i) => {
      const d = Math.hypot(a.x - x, a.y - y)
      if (d < dist) [best, dist] = [i, d]
    })
    if (best >= 0) setSel(best)
  }

  const many = scene.actors.length > 1
  const actor = scene.actors[sel]
  const sheet = actor ? scene.sheets[actor.sheet] : undefined

  const toolbar = (
    <>
      <ToolGroup>
        <ToolButton title={playing ? 'Pause' : 'Play'} onClick={() => setPlaying((p) => !p)}>
          {playing ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
        </ToolButton>
        <ToolButton title="One tick" onClick={stepOnce}>
          <StepForward className="w-3.5 h-3.5" />
        </ToolButton>
        <ToolButton title="Restart every actor's anim" onClick={restart}>
          <RotateCcw className="w-3.5 h-3.5" />
        </ToolButton>
        <select
          value={speed}
          onChange={(e) => setSpeed(Number(e.target.value))}
          className="h-6 rounded border border-stage-border bg-stage px-1 text-[11px] font-mono text-stage-foreground cursor-pointer"
          title="Speed — 1× is the game's 59.94 ticks a second"
        >
          {SPEEDS.map((v) => (
            <option key={v} value={v}>
              {v === 0.25 ? '¼' : v === 0.5 ? '½' : v}×
            </option>
          ))}
        </select>
      </ToolGroup>
      <ToolGroup>
        <ToolButton title="Show actor anchors" active={anchors} onClick={() => setAnchors((v) => !v)}>
          <Crosshair className="w-3.5 h-3.5" />
        </ToolButton>
        <ToolButton title="Show actor labels" active={labels} onClick={() => setLabels((v) => !v)}>
          <Tag className="w-3.5 h-3.5" />
        </ToolButton>
        {common.length > 0 && (
          <select
            value=""
            onChange={(e) => e.target.value !== '' && playAll(Number(e.target.value))}
            className="h-6 w-28 rounded border border-stage-border bg-stage px-1 text-[11px] text-stage-foreground cursor-pointer"
            title="Play one anim on every actor"
          >
            <option value="">All play…</option>
            {common.map((c) => (
              <option key={c.id} value={c.id}>
                {c.id}
                {c.name ? ` · ${c.name}` : ''}
              </option>
            ))}
          </select>
        )}
        <TickReadout ticks={ticks} hz={scene.tickHz} />
      </ToolGroup>
      {actions && <ToolGroup>{actions}</ToolGroup>}
    </>
  )

  const render = (z: number) => (
    <>
      <canvas
        ref={canvas}
        width={scene.w}
        height={scene.h}
        className={cn('absolute left-0 top-0', z >= 1 && 'pixelated')}
        style={{ width: scene.w * z, height: scene.h * z }}
      />
      {failed && (
        <span className="absolute inset-0 flex items-center justify-center text-[11px] text-white/70 pointer-events-none">
          the pose sheets did not load
        </span>
      )}
      {many && actor && sheet && <SelectionBox a={actor} sh={sheet} z={z} />}
      {anchors &&
        scene.actors.map((a, i) => (
          <span
            key={i}
            className={cn('absolute pointer-events-none', i === sel ? 'text-primary' : 'text-white/80')}
            style={{ left: a.x * z - 4, top: a.y * z - 4, width: 9, height: 9 }}
          >
            <span className="absolute left-1 top-0 h-full w-px bg-current" />
            <span className="absolute top-1 left-0 w-full h-px bg-current" />
          </span>
        ))}
      {labels &&
        scene.actors.map((a, i) => {
          const sh = scene.sheets[a.sheet]
          const b = cellBox(a, sh)
          const grid = scene.depth === 'order'
          return (
            <span
              key={i}
              className={cn(
                'absolute pointer-events-none -translate-x-1/2 whitespace-nowrap rounded px-1 text-[10px] font-mono leading-tight',
                i === sel && many ? 'bg-primary text-primary-foreground' : 'bg-black/70 text-stage-foreground',
              )}
              style={{ left: (grid ? b.left + b.w / 2 : a.x) * z, top: (grid ? b.top + b.h : a.y) * z + 2 }}
            >
              {a.label}
            </span>
          )
        })}
    </>
  )

  return (
    <div className="flex-1 min-w-0 min-h-0 flex flex-col">
      <PixelView
        picture={{ layers: stills, custom: { key: ident, w: scene.w, h: scene.h, render } }}
        grid={false}
        onExport={onExport}
        toolbarStart={toolbar}
        onPixelClick={pick}
        memory={memory}
      />
      {actor && sheet && (
        <AnimStrip
          actor={actor}
          sheet={sheet}
          engine={engines[sel]}
          many={many}
          hz={scene.tickHz}
          note={scene.tickNote}
          advanced={advanced}
          onPlay={(id) => playOn(sel, id)}
        />
      )}
    </div>
  )
}

/** An anim's name: in Fan mode a fan's words for it, in Advanced the
 *  battle census's (the status bits the code tests). */
function animName(def: AnimDef, advanced: boolean): string | null {
  return (advanced ? def.name : (def.fanName ?? def.name)) ?? null
}

function TickReadout({ ticks, hz }: { ticks: React.RefObject<number>; hz: number }) {
  const t = Number(useLive(() => String(ticks.current)))
  return (
    <span className="text-[11px] font-mono text-stage-muted ml-2 whitespace-nowrap" title={`ticks since the scene opened, at ${hz} Hz`}>
      t {t} · {(t / hz).toFixed(2)}s
    </span>
  )
}

function SelectionBox({ a, sh, z }: { a: SceneActor; sh: SceneSheet; z: number }) {
  const b = cellBox(a, sh)
  return (
    <span
      className="absolute pointer-events-none border border-dashed border-primary/70"
      style={{ left: b.left * z, top: b.top * z, width: b.w * z, height: b.h * z }}
    />
  )
}

/**
 * The picked actor's anim table: every anim as a chip (named where the
 * battle census names it), and the playing one's steps as a timeline whose
 * widths are the steps' tick counts.
 */
function AnimStrip({
  actor,
  sheet,
  engine,
  many,
  hz,
  note,
  advanced,
  onPlay,
}: {
  actor: SceneActor
  sheet: SceneSheet
  engine: ActorAnim
  many: boolean
  hz: number
  note: string
  advanced: boolean
  onPlay: (id: number) => void
}) {
  const state = useLive(() => `${engine.anim}:${engine.step}:${engine.timer}`)
  const [anim, step, timer] = state.split(':').map(Number)
  const def = sheet.anims[anim]
  const total = def ? def.steps.reduce((n, s) => n + s[1], 0) : 0

  return (
    <div className="shrink-0 max-h-[40%] overflow-y-auto border-t border-stage-border bg-stage-raised text-stage-foreground px-3 py-2 space-y-2">
      <div className="flex items-baseline gap-2 text-[11px]">
        <span className="font-semibold font-mono">{actor.label}</span>
        <span className="text-stage-muted font-mono">{sheet.label}</span>
        {many && <span className="text-stage-muted">· click an actor to pick it</span>}
        <span className="flex-1" />
        {def && (
          <span className="font-mono text-stage-muted">
            anim {anim}
            {animName(def, advanced) ? ` · ${animName(def, advanced)}` : ''} · {def.hold ? 'hold' : 'loop'} · step {Math.min(step, def.steps.length - 1) + 1}/{def.steps.length} ·{' '}
            {total} t = {(total / hz).toFixed(2)}s
          </span>
        )}
      </div>
      <div className="flex flex-wrap gap-1">
        {sheet.anims.map((a) => {
          const empty = a.steps.length === 0
          return (
            <button
              key={a.index}
              disabled={empty}
              onClick={() => onPlay(a.index)}
              title={
                empty
                  ? `anim ${a.index}: no steps`
                  : `anim ${a.index}${animName(a, advanced) ? ` — ${animName(a, advanced)}` : ''}: ${a.steps.length} steps, ${a.hold ? 'holds its last step' : 'loops'}${advanced && a.proof ? `\nplayed by ${a.proof}` : ''}`
              }
              className={cn(
                'h-6 px-1.5 rounded border text-[10px] font-mono flex items-center gap-1 max-w-56',
                empty
                  ? 'border-stage-border/50 text-stage-muted/50 cursor-default'
                  : a.index === anim
                    ? 'bg-primary text-primary-foreground border-primary cursor-pointer'
                    : 'border-stage-border text-stage-foreground hover:bg-white/10 cursor-pointer',
              )}
            >
              <span className="font-semibold">{a.index}</span>
              {animName(a, advanced) && <span className="truncate">{animName(a, advanced)}</span>}
            </button>
          )
        })}
      </div>
      {def && def.steps.length > 0 && (
        <div>
          <div className="flex gap-px h-7">
            {def.steps.map(([pose, dur], i) => {
              const here = i === Math.min(step, def.steps.length - 1)
              const frac = here && dur > 0 ? Math.min(1, timer / dur) : 0
              return (
                <div
                  key={i}
                  className={cn(
                    'relative min-w-[18px] rounded-sm overflow-hidden flex flex-col items-center justify-center text-[9px] font-mono leading-none',
                    here ? 'bg-primary/30 text-white ring-1 ring-primary' : 'bg-stage text-stage-muted',
                  )}
                  style={{ flexGrow: Math.max(1, dur), flexBasis: 0 }}
                  title={`step ${i + 1}: pose ${pose} for ${dur} ticks (${((dur / hz) * 1000).toFixed(0)} ms)`}
                >
                  {here && <span className="absolute left-0 bottom-0 h-0.5 bg-primary" style={{ width: `${frac * 100}%` }} />}
                  <span>p{pose}</span>
                  <span className="opacity-70">{dur}</span>
                </div>
              )
            })}
          </div>
          {advanced && (
            <p className="text-[10px] text-stage-muted mt-1">
              {def.proof ? `played by ${def.proof} · ` : ''}
              {note}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
