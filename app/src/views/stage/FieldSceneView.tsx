import { ArrowLeft, BookMarked, Download, Grid3x3, IdCard, Pause, Play, RotateCcw, StepForward, Users } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import type { BgChangeRow, FieldTilesetPage, Layer, Scene, SceneActor, SceneSheet } from '../../lib/api'
import { storyWords, type Rect } from '../../lib/game/bgChange'
import { drawItems, pointAt, shownAt } from '../../lib/game/fieldScene'
import { CELL, Ground } from '../../lib/game/ground'
import { PaletteAnimator } from '../../lib/game/paletteAnimation'
import { useLive, useStored } from '../../lib/hooks'
import { nav } from '../../lib/nav'
import { loadImage, pixels } from '../../lib/sceneImages'
import { cn } from '../../lib/utils'
import { ObjectsPanel, StoryPanel } from './MapPanels'
import { MapExport, type Parts } from './MapExport'
import { GROUP_TONE } from './mapStyle'
import { PixelView, ToolButton } from './PixelView'
import { ToolGroup, Toolbar } from './Toolbar'

const SPEEDS = [0.25, 0.5, 1, 2, 4]
/** A long stall (a hidden window) must not replay minutes of ticks at once. */
const MAX_TICKS_PER_FRAME = 32
/** The ground's own layers, beside the scene's groups of actors. */
const BACK = 'back'
const TILES = 'tiles'
const ROOFS = 'roofs'
interface Loaded {
  ground: Ground
  sheets: HTMLImageElement[]
  alpha: (ImageData | null)[]
  /** Row 501 as the palette animation leaves it, by tick. */
  colours: PaletteAnimator | null
  /** The In game view's mask, and its pixels to ask what is hidden. */
  mask: HTMLImageElement | null
  seen: ImageData | null
}

/** The actors' group the party is in (backend field_view.PARTY). */
const PARTY = 'the party'

/** The box an actor's cell covers at a point of its track. */
function cellBox(sh: SceneSheet, x: number, y: number) {
  return { left: x - sh.anchorX, top: y - sh.anchorY, w: sh.cellW, h: sh.cellH }
}

/**
 * A field map played from the tracks the backend baked
 * (backend/viewer_tabs/field_view.py `played`): each actor's position, pose
 * and class tick by tick, drawn every tick by the field's rules
 * (lib/game/fieldScene.ts) over the ground the client draws from the map's
 * own tile words, pages and CLUT rows (lib/game/ground.ts). The bar above
 * shows or hides each layer and opens the Tileset (the stage swaps to the
 * pages) and the Objects panel (along the map's right edge). Raw shows the
 * whole plane; In game blacks out what the camera never shows
 * (backend formats/map_reach.py) and fits the view to the rest.
 */
export function FieldSceneView({
  scene,
  stills,
  onExport,
  memory,
  actions,
  title,
  disc,
  onSave,
  onDrawn,
  advanced = false,
}: {
  scene: Scene
  /** Server-rendered pictures: the map at tick 0, then the tileset's pages. Export writes them. */
  stills: Layer[]
  onExport?: (layer: number, all: boolean) => void
  memory: string
  /** After the playback controls: the map's music button. */
  actions?: ReactNode
  /** The map's name, for its export. */
  title: string
  /** The disc it is read from: the objects' cards are that disc's. */
  disc?: string
  /** Save a picture of the map under its exports folder (MapExport): the path. */
  onSave?: (name: string, png: Blob, scale: number) => Promise<string>
  /** Told this scene once its first frame is drawn (or its pictures failed),
   *  and null when the view goes: the stage says it is decoding till then. */
  onDrawn?: (scene: Scene | null) => void
  /** Advanced mode: the footer cites the field's clock, and a picked
   *  object says how it is made (its row, kind, think, sprite data). */
  advanced?: boolean
}) {
  const field = scene.field!
  const [loaded, setLoaded] = useState<Loaded | null>(null)
  const [failed, setFailed] = useState<string | null>(null)
  const [playing, setPlaying] = useState(true)
  const [speed, setSpeed] = useStored('scene.speed', 1)
  const [labels, setLabels] = useStored('map.labels', false)
  const [hiddenList, setHiddenList] = useStored<string[]>('map.hidden', [])
  const [panel, setPanel] = useStored<'objects' | 'story' | null>('map.panel', null)
  const [mapView, setMapView] = useStored<'raw' | 'game'>('map.view', 'game')
  const reach = field.reach
  const inGame = mapView === 'game' && !!reach
  const [tileset, setTileset] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [sel, setSel] = useState(-1)
  // The story: bits set, bit-less changes opened, a change being played
  // (from the absolute tick it started), and the rectangle hovered.
  const [bits, setBits] = useState<Set<number>>(() => new Set())
  const [doors, setDoors] = useState<Set<number>>(() => new Set())
  const [hoverRect, setHoverRect] = useState<Rect | null>(null)
  const play = useRef<{ row: BgChangeRow; start: number } | null>(null)
  const wordsKey = useRef('')
  const [focus, setFocus] = useState<{ x: number; y: number; n: number } | undefined>()
  const canvas = useRef<HTMLCanvasElement | null>(null)
  const ticks = useRef(0)
  const redraw = useRef(true)
  const live = useRef({ playing, speed, tileset })
  useEffect(() => {
    live.current = { playing, speed, tileset }
  }, [playing, speed, tileset])

  const hidden = useMemo(() => new Set(hiddenList), [hiddenList])
  const ident = useMemo(() => `${field.ground.blob}|${scene.sheets.map((s) => s.blob).join(',')}|${scene.actors.length}`, [scene, field])

  // (Stage keys this view by result, so a new selection starts fresh.)
  useEffect(() => {
    let alive = true
    Promise.all([
      Ground.load(field.ground),
      Promise.all(scene.sheets.map((s) => loadImage(s.blob))),
      field.reach ? loadImage(field.reach.mask) : Promise.resolve(null),
    ])
      .then(([ground, sheets, mask]) => {
        const { palette, rows } = field.ground
        const colours = palette && rows[1] ? new PaletteAnimator(rows[1], palette) : null
        if (!alive) return
        setLoaded({ ground, sheets, alpha: sheets.map(pixels), colours, mask, seen: mask && pixels(mask) })
        // Open where the camera starts: on the lead.
        const lead = scene.actors.find((a) => a.group === PARTY && a.track)
        if (lead) {
          const [, x, y] = pointAt(lead.track!, 0)
          setFocus((f) => ({ x, y, n: (f?.n ?? 0) + 1 }))
        }
      })
      .catch((e) => {
        if (!alive) return
        setFailed(e instanceof Error ? e.message : 'the field pictures did not load')
        onDrawn?.(scene)
      })
    return () => {
      alive = false
    }
  }, [scene, field, onDrawn])
  useEffect(() => () => onDrawn?.(null), [onDrawn])

  /** The map at tick `t` into `g`, drawing `parts` (the hidden groups
   *  stay hidden): the view's picture, and an export's. */
  const paint = useCallback(
    (g: CanvasRenderingContext2D, t: number, parts: Parts) => {
      if (!loaded) return
      const { ground } = loaded
      // (the ground's own layers are drawn into its canvas)
      ground.layers(parts.back, parts.tiles)
      // The story's copies, from the map as it loads: a row being played
      // shows the source its clock has reached.
      const p = play.current
      const k = p ? Math.max(0, Math.min(Math.floor((ticks.current - p.start) / p.row.frames), p.row.sources.length - 1)) : -1
      const key = `${[...bits].join(',')}|${[...doors].join(',')}|${p ? `${p.row.id}:${k}` : ''}`
      if (key !== wordsKey.current) {
        wordsKey.current = key
        const on = (r: BgChangeRow) =>
          p && p.row.id === r.id ? k : (r.bit !== null && bits.has(r.bit)) || (r.bit === null && doors.has(r.id)) ? r.sources.length - 1 : -1
        ground.setWords(storyWords(ground.baseWords, field.story.rows, on))
      }
      ground.setTick(t)
      if (loaded.colours) ground.setRow(1, loaded.colours.at(t))
      ground.flush()
      g.imageSmoothingEnabled = false
      g.globalAlpha = 1
      g.clearRect(0, 0, g.canvas.width, g.canvas.height)
      g.drawImage(ground.groundCanvas, 0, 0)
      const roofs = parts.roofs ? (k: number) => ground.isRoof(k) : () => false
      const shown = parts.sprites ? shownAt(scene.actors, t, hidden, bits) : []
      for (const it of drawItems(shown, scene.actors, scene.sheets, roofs, field.ground.columns)) {
        if (it.cell) {
          const x = it.cell[0] * CELL
          const y = it.cell[1] * CELL
          g.drawImage(ground.roofCanvas, x, y, CELL, CELL, x, y, CELL, CELL)
          if (ground.roofStpCanvas) {
            g.globalAlpha = 0.5
            g.drawImage(ground.roofStpCanvas, x, y, CELL, CELL, x, y, CELL, CELL)
            g.globalAlpha = 1
          }
          continue
        }
        const s = it.shown!
        const a = scene.actors[s.i]
        const sh = scene.sheets[a.sheet]
        const sx = (s.pose % sh.columns) * sh.cellW
        const sy = Math.floor(s.pose / sh.columns) * sh.cellH
        g.globalAlpha = a.semi ? 0.5 : 1
        g.drawImage(loaded.sheets[a.sheet], sx, sy, sh.cellW, sh.cellH, s.x - sh.anchorX, s.y - sh.anchorY, sh.cellW, sh.cellH)
        g.globalAlpha = 1
      }
      // In game: what the camera never shows goes black, over everything.
      if (parts.mask && loaded.mask && reach) {
        g.drawImage(loaded.mask, 0, 0, loaded.mask.width * reach.scale, loaded.mask.height * reach.scale)
      }
    },
    [loaded, scene, field, hidden, bits, doors, reach],
  )

  const noBack = !field.ground.layer2
  const shownParts = useMemo<Parts>(
    () => ({ back: !noBack && !hidden.has(BACK), tiles: !hidden.has(TILES), roofs: !hidden.has(ROOFS), sprites: true, mask: inGame }),
    [noBack, hidden, inGame],
  )

  const draw = useCallback(
    (t: number) => {
      const c = canvas.current
      if (c) paint(c.getContext('2d')!, t, shownParts)
    },
    [paint, shownParts],
  )

  /** The whole plane at the tick on screen (a tick of the loop, as the
   *  frame loop draws it), for an export. */
  const drawPlane = useCallback(
    (parts: Parts) => {
      const c = document.createElement('canvas')
      c.width = scene.w
      c.height = scene.h
      paint(c.getContext('2d')!, ticks.current % field.ticks, parts)
      // the view's own picture is drawn again with its own parts
      redraw.current = true
      return c
    },
    [paint, scene, field.ticks],
  )

  /** In game: whether the camera ever shows map pixel (x, y). */
  const visible = useCallback(
    (x: number, y: number) => {
      const seen = loaded?.seen
      if (!inGame || !seen || !reach) return true
      const mx = Math.floor(x / reach.scale)
      const my = Math.floor(y / reach.scale)
      if (mx < 0 || my < 0 || mx >= seen.width || my >= seen.height) return false
      return seen.data[(my * seen.width + mx) * 4 + 3] === 0
    },
    [loaded, inGame, reach],
  )

  // The frame loop: whole ticks at the scene's rate, scaled by the speed;
  // a picture only when the tick (or what is shown) changed.
  useEffect(() => {
    if (!loaded) return
    const tickMs = 1000 / scene.tickHz
    let raf = 0
    let last = performance.now()
    let acc = 0
    let drawn = -1
    let first = true
    redraw.current = true
    const frame = (now: number) => {
      const dt = now - last
      last = now
      if (live.current.playing) {
        acc += dt * live.current.speed
        let n = 0
        while (acc >= tickMs && n < MAX_TICKS_PER_FRAME) {
          ticks.current++
          acc -= tickMs
          n++
        }
        if (n === MAX_TICKS_PER_FRAME) acc = 0
      }
      const t = ticks.current % field.ticks
      if (!live.current.tileset && (t !== drawn || redraw.current)) {
        draw(t)
        drawn = t
        redraw.current = false
      }
      if (first) {
        first = false
        onDrawn?.(scene)
      }
      raf = requestAnimationFrame(frame)
    }
    raf = requestAnimationFrame(frame)
    return () => cancelAnimationFrame(raf)
  }, [loaded, draw, scene, field.ticks, onDrawn])

  const stepOnce = () => {
    setPlaying(false)
    ticks.current++
  }
  const restart = () => {
    ticks.current = 0
    redraw.current = true
  }
  const toggle = (key: string) => setHiddenList((old) => (old.includes(key) ? old.filter((k) => k !== key) : [...old, key]))

  // Pick a body by its ink, topmost first; else the nearest anchor.
  const pick = (x: number, y: number) => {
    if (!loaded) return
    if (!visible(x, y)) return setSel(-1)
    const t = ticks.current % field.ticks
    const bodies = drawItems(shownAt(scene.actors, t, hidden, bits), scene.actors, scene.sheets, () => false, field.ground.columns)
      .filter((it) => it.shown && !scene.actors[it.shown.i].twin && visible(it.shown.x, it.shown.y))
      .map((it) => it.shown!)
      .reverse()
    for (const s of bodies) {
      const sh = scene.sheets[scene.actors[s.i].sheet]
      const b = cellBox(sh, s.x, s.y)
      if (x < b.left || y < b.top || x >= b.left + b.w || y >= b.top + b.h) continue
      const px = (s.pose % sh.columns) * sh.cellW + (x - b.left)
      const py = Math.floor(s.pose / sh.columns) * sh.cellH + (y - b.top)
      const data = loaded.alpha[scene.actors[s.i].sheet]
      if (data && px < data.width && py < data.height && data.data[(py * data.width + px) * 4 + 3] > 0) return setSel(s.i)
    }
    let best = -1
    let dist = 24
    for (const s of bodies) {
      const d = Math.hypot(s.x - x, s.y - y)
      if (d < dist) [best, dist] = [s.i, d]
    }
    setSel(best)
  }

  // From the Objects panel: select the body and bring it into view.
  const pickActor = (i: number) => {
    setSel(i)
    const [, x, y] = pointAt(scene.actors[i].track!, ticks.current % field.ticks)
    setFocus((f) => ({ x, y, n: (f?.n ?? 0) + 1 }))
  }
  const focusAt = useCallback((x: number, y: number, actor?: number) => {
    if (actor !== undefined) setSel(actor)
    setFocus((f) => ({ x, y, n: (f?.n ?? 0) + 1 }))
  }, [])
  const onBits = useCallback((keys: number[], on: boolean) => setBits((old) => toggled(old, keys, on)), [])
  const onDoors = useCallback((keys: number[], on: boolean) => setDoors((old) => toggled(old, keys, on)), [])
  const onBit = useCallback((bit: number, on: boolean) => onBits([bit], on), [onBits])
  // Play a change from the map as it loads: the row's copies one source
  // at a time; it stays open (its bit set) when they are done.
  const onPlay = useCallback(
    (row: BgChangeRow) => {
      play.current = { row, start: ticks.current }
      if (row.bit !== null) onBits([row.bit], true)
      else onDoors([row.id], true)
      setPlaying(true)
    },
    [onBits, onDoors],
  )

  const playback = (
    <>
      <ToolGroup>
        <ToolButton title={playing ? 'Pause' : 'Play'} onClick={() => setPlaying((p) => !p)}>
          {playing ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
        </ToolButton>
        <ToolButton title="One tick" onClick={stepOnce}>
          <StepForward className="w-3.5 h-3.5" />
        </ToolButton>
        <ToolButton title="Back to tick 0" onClick={restart}>
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
        <LoopReadout ticks={ticks} loop={field.ticks} hz={scene.tickHz} />
      </ToolGroup>
      {actions && <ToolGroup>{actions}</ToolGroup>}
    </>
  )

  // The bar's right-hand side: the views that take the stage or a panel.
  const panelButtons = (
    <ToolGroup>
      <PanelButton icon={<Grid3x3 className="w-3.5 h-3.5" />} active={false} onClick={() => setTileset(true)} title="The texture pages this map loads, through each CLUT">
        Tileset
      </PanelButton>
      <PanelButton
        icon={<BookMarked className="w-3.5 h-3.5" />}
        active={panel === 'story'}
        count={field.story.bits.length}
        onClick={() => setPanel((p) => (p === 'story' ? null : 'story'))}
        title="The story flags that change this map, its doors and its other tile changes"
      >
        Story flags
      </PanelButton>
      <PanelButton
        icon={<Users className="w-3.5 h-3.5" />}
        active={panel === 'objects'}
        count={field.objects.length}
        onClick={() => setPanel((p) => (p === 'objects' ? null : 'objects'))}
        title="Every object the map's object set makes, and the party"
      >
        Objects
      </PanelButton>
    </ToolGroup>
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
      {failed && <span className="absolute inset-0 flex items-center justify-center text-[11px] text-white/70 pointer-events-none">{failed}</span>}
      <Overlay scene={scene} ticks={ticks} hidden={hidden} bits={bits} labels={labels} sel={sel} rect={hoverRect} z={z} visible={visible} />
    </>
  )

  return (
    <div className="flex-1 min-w-0 min-h-0 flex flex-col bg-stage">
      {tileset && <TilesetStage pages={field.tileset} stills={stills} onExport={onExport} memory={`${memory}.tileset`} onBack={() => setTileset(false)} />}
      {exporting && onSave && (
        <MapExport
          title={title}
          inGame={inGame}
          reach={reach ?? null}
          shown={shownParts}
          hasBack={!noBack}
          size={{ w: scene.w, h: scene.h }}
          tileset={stills.slice(1)}
          draw={drawPlane}
          save={onSave}
          onClose={() => setExporting(false)}
        />
      )}
      <div className={cn('flex-1 min-h-0 flex flex-col', tileset && 'hidden')}>
        <Toolbar end={panelButtons}>
          <ToolGroup>
            <Tab on={!inGame} onClick={() => setMapView('raw')} title="The whole plane as the map file holds it, the areas the game never shows included">
              Raw
            </Tab>
            <Tab
              on={inGame}
              disabled={!reach}
              onClick={() => setMapView('game')}
              title={
                reach
                  ? 'What a player can see: the camera following the lead from every way in, the rest black'
                  : 'No way in reaches this map: there is nothing to follow'
              }
            >
              In game
            </Tab>
          </ToolGroup>
          <ToolGroup>
            <span className="text-[10px] uppercase tracking-wide font-semibold text-stage-muted mr-1">Show</span>
            <Chip
              on={!noBack && !hidden.has(BACK)}
              disabled={noBack}
              onClick={() => toggle(BACK)}
              title={noBack ? 'This map draws no second layer behind its tiles' : 'The second layer, behind the tiles'}
            >
              Back
            </Chip>
            <Chip on={!hidden.has(TILES)} onClick={() => toggle(TILES)} title="The tile layer (bg_first_draw)">
              Tiles
            </Chip>
            <Chip on={!hidden.has(ROOFS)} onClick={() => toggle(ROOFS)} title="The roofs' second copies, over whatever stands under them">
              Roofs
            </Chip>
            {field.groups.map(([g, short]) => (
              <Chip key={g} on={!hidden.has(g)} onClick={() => toggle(g)} title={`${hidden.has(g) ? 'Show' : 'Hide'} ${g}`} tone={GROUP_TONE[short]}>
                {short}
              </Chip>
            ))}
            <Chip on={labels} onClick={() => setLabels((v) => !v)} title="Each row's number over it">
              Labels
            </Chip>
          </ToolGroup>
        </Toolbar>
        <PixelView
          picture={{
            layers: stills.slice(0, 1),
            custom:
              inGame && reach
                ? {
                    key: ident,
                    w: reach.bbox[2] - reach.bbox[0],
                    h: reach.bbox[3] - reach.bbox[1],
                    origin: { x: reach.bbox[0], y: reach.bbox[1] },
                    render,
                  }
                : { key: ident, w: scene.w, h: scene.h, render },
          }}
          grid={false}
          toolbarStart={playback}
          toolbarEnd={
            onSave && (
              <ToolButton title="Save pictures of the map: as shown, each area, its layers apart, its tileset" active={exporting} onClick={() => setExporting(true)} wide>
                <Download className="w-3.5 h-3.5" />
                <span className="text-[11px]">Export</span>
              </ToolButton>
            )
          }
          onPixelClick={pick}
          focus={focus}
          memory={memory}
          side={
            <>
              {panel === 'objects' && <ObjectsPanel objects={field.objects} sel={sel} bits={bits} disc={disc} onPick={pickActor} onBit={onBit} onClose={() => setPanel(null)} />}
              {panel === 'story' && (
                <StoryPanel
                  story={field.story}
                  actors={scene.actors}
                  objects={field.objects}
                  bits={bits}
                  doors={doors}
                  onBits={onBits}
                  onDoors={onDoors}
                  onPlay={onPlay}
                  onHover={setHoverRect}
                  onFocus={focusAt}
                  disc={disc}
                  onClose={() => setPanel(null)}
                />
              )}
            </>
          }
        />
        <Picked scene={scene} ticks={ticks} sel={sel} disc={disc} advanced={advanced} />
      </div>
    </div>
  )
}

/** A layer shown (lit) or hidden (struck through). */
function Chip({
  on,
  disabled,
  tone,
  title,
  onClick,
  children,
}: {
  on: boolean
  disabled?: boolean
  tone?: string
  title: string
  onClick: () => void
  children: ReactNode
}) {
  return (
    <button
      title={title}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        'h-6 px-2 rounded-md border text-[11px] whitespace-nowrap cursor-pointer transition-colors shrink-0 disabled:cursor-default disabled:opacity-35',
        on ? cn('border-stage-border bg-white/10 hover:bg-white/15', tone ?? 'text-stage-foreground') : 'border-stage-border/50 text-stage-muted/70 line-through hover:text-stage-muted',
      )}
    >
      {children}
    </button>
  )
}

function PanelButton({
  icon,
  active,
  count,
  title,
  onClick,
  children,
}: {
  icon: ReactNode
  active: boolean
  count?: number
  title: string
  onClick: () => void
  children: ReactNode
}) {
  return (
    <button
      title={title}
      onClick={onClick}
      className={cn(
        'h-7 px-2 rounded flex items-center gap-1.5 text-[11px] cursor-pointer transition-colors shrink-0',
        active ? 'bg-primary/20 text-primary' : 'text-stage-foreground/85 hover:bg-white/10 hover:text-white',
      )}
    >
      {icon}
      {children}
      {count !== undefined && <span className="rounded bg-white/10 px-1 font-mono text-[10px] text-stage-foreground/80">{count}</span>}
    </button>
  )
}

function LoopReadout({ ticks, loop, hz }: { ticks: React.RefObject<number>; loop: number; hz: number }) {
  const t = Number(useLive(() => String(ticks.current % loop)))
  return (
    <span className="text-[11px] font-mono text-stage-muted ml-2 whitespace-nowrap" title={`ticks into the loop of ${loop}, at ${hz} a second`}>
      t {t}/{loop} · {(t / hz).toFixed(2)}s
    </span>
  )
}

/** The objects' labels and the picked object's box, where they stand this tick. */
function Overlay({
  scene,
  ticks,
  hidden,
  bits,
  labels,
  sel,
  rect,
  z,
  visible,
}: {
  scene: Scene
  ticks: React.RefObject<number>
  hidden: Set<string>
  bits: Set<number>
  labels: boolean
  sel: number
  /** A bg change's rectangle, outlined. */
  rect: Rect | null
  z: number
  /** Whether a map pixel is shown (In game hides some). */
  visible: (x: number, y: number) => boolean
}) {
  const loop = scene.field!.ticks
  const t = Number(useLive(() => String(labels || sel >= 0 ? ticks.current % loop : 0)))
  const at = (a: SceneActor) => pointAt(a.track!, t)
  const picked = sel >= 0 ? scene.actors[sel] : undefined
  return (
    <>
      {rect && (
        <span
          className="absolute pointer-events-none border-2 border-dashed border-amber-300 bg-amber-300/10"
          style={{ left: rect[0] * z, top: rect[1] * z, width: rect[2] * z, height: rect[3] * z }}
        />
      )}
      {picked &&
        (() => {
          const [, x, y, pose] = at(picked)
          if (pose < 0) return null
          const b = cellBox(scene.sheets[picked.sheet], x, y)
          return (
            <span
              className="absolute pointer-events-none border border-dashed border-primary/70"
              style={{ left: b.left * z, top: b.top * z, width: b.w * z, height: b.h * z }}
            />
          )
        })()}
      {labels &&
        scene.actors.map((a, i) => {
          if (!a.label || (a.group && hidden.has(a.group)) || (a.out != null && bits.has(a.out))) return null
          const [, x, y, pose] = at(a)
          if (pose < 0 || !visible(x, y)) return null
          return (
            <span
              key={i}
              className={cn(
                'absolute pointer-events-none -translate-x-1/2 whitespace-nowrap rounded px-1 text-[10px] font-mono leading-tight',
                i === sel ? 'bg-primary text-primary-foreground' : 'bg-black/70 text-stage-foreground',
              )}
              style={{ left: x * z, top: y * z + 2 }}
            >
              {a.label}
            </span>
          )
        })}
    </>
  )
}

/** The picked object: what it is, and where it stands this tick. */
function Picked({ scene, ticks, sel, disc, advanced }: { scene: Scene; ticks: React.RefObject<number>; sel: number; disc?: string; advanced: boolean }) {
  const loop = scene.field!.ticks
  const t = Number(useLive(() => String(ticks.current % loop)))
  const a = sel >= 0 ? scene.actors[sel] : undefined
  if (!a) {
    return (
      <div className="shrink-0 border-t border-stage-border bg-stage-raised text-stage-muted px-3 py-2 text-[11px]">
        click someone or something to see what it is
        {advanced && ` · ${scene.tickNote}`}
      </div>
    )
  }
  const [since, x, y, pose, klass] = pointAt(a.track!, t)
  const ref = scene.field!.objects.find((o) => o.actor === sel)?.ref
  return (
    <div className="shrink-0 border-t border-stage-border bg-stage-raised text-stage-foreground px-3 py-2 space-y-1 text-[11px]">
      <div className="flex items-baseline gap-2">
        <span className="font-semibold font-mono">{advanced ? (a.note ?? a.label) : a.label || a.note}</span>
        {ref && disc && (
          <button
            className="ml-auto h-6 px-1.5 rounded flex items-center gap-1 text-stage-foreground/85 hover:bg-white/10 hover:text-white cursor-pointer"
            title="Open its card: what it is, and everything it links to"
            onClick={() => nav.open(ref, disc)}
          >
            <IdCard className="w-3.5 h-3.5" /> Open card
          </button>
        )}
      </div>
      {advanced && (
        <div className="font-mono text-stage-muted">
          ({x}, {y}) · pose {pose} · class {'0x' + klass.toString(16)} · since tick {since} · {a.track!.length} changes in the loop ·{' '}
          {scene.sheets[a.sheet].label}
        </div>
      )}
    </div>
  )
}

/** The map's texture pages, the stage swapped from the map: a page, then
 *  the CLUT that draws it. Export writes the page as shown. */
function TilesetStage({
  pages,
  stills,
  onExport,
  memory,
  onBack,
}: {
  pages: FieldTilesetPage[]
  stills: Layer[]
  onExport?: (layer: number, all: boolean) => void
  memory: string
  onBack: () => void
}) {
  const [pageIx, setPageIx] = useStored('map.tileset.page', 0)
  const [rowIx, setRowIx] = useState(0)
  const page = pages[Math.min(pageIx, pages.length - 1)]
  const row = page?.rows[Math.min(rowIx, page.rows.length - 1)]
  const used = page?.rows.filter((r) => r.uses > 0) ?? []
  const unused = page?.rows.filter((r) => r.uses === 0) ?? []
  const layer = row ? stills[row.layer] : undefined
  const choose = (p: number) => {
    setPageIx(p)
    setRowIx(0)
  }
  return (
    <div className="flex-1 min-h-0 flex flex-col">
      <Toolbar>
        <ToolGroup>
          <button className="h-7 px-2 rounded flex items-center gap-1.5 text-[11px] cursor-pointer text-stage-foreground/85 hover:bg-white/10 hover:text-white shrink-0" title="Back to the map" onClick={onBack}>
            <ArrowLeft className="w-3.5 h-3.5" /> Map
          </button>
        </ToolGroup>
        <ToolGroup>
          {pages.map((p, i) => (
            <Tab key={p.page} on={p === page} onClick={() => choose(i)}>
              {p.label}
            </Tab>
          ))}
        </ToolGroup>
        <ToolGroup>
          {page &&
            (page.rows.length <= 2 ? page.rows : used).map((r) => (
              <Tab key={r.label} on={r === row} onClick={() => setRowIx(page.rows.indexOf(r))} title={`${r.uses} ${r.what} of the map are drawn through ${r.label}`}>
                {r.label} <span className="font-mono text-[10px] opacity-70">{r.uses}</span>
              </Tab>
            ))}
          {page && page.rows.length > 2 && unused.length > 0 && (
            <select
              value={row && row.uses === 0 ? page.rows.indexOf(row) : ''}
              onChange={(e) => setRowIx(Number(e.target.value))}
              className="h-6 rounded border border-stage-border bg-stage px-1 text-[11px] text-stage-foreground cursor-pointer shrink-0"
              title="CLUTs no cell of this map draws through"
            >
              <option value="" disabled>
                {unused.length} unused
              </option>
              {unused.map((r) => (
                <option key={r.label} value={page.rows.indexOf(r)}>
                  {r.label}
                </option>
              ))}
            </select>
          )}
        </ToolGroup>
        {!!page?.notes.length && (
          <ToolGroup>
            {page.notes.map((n) => (
              <span key={n} className="min-w-0 text-[10px] text-warn">
                {n}
              </span>
            ))}
          </ToolGroup>
        )}
      </Toolbar>
      {layer ? (
        <PixelView picture={{ layers: [layer] }} grid onExport={onExport && row ? () => onExport(row.layer, false) : undefined} memory={memory} />
      ) : (
        <div className="flex-1 flex items-center justify-center text-[11px] text-stage-muted">This map loads no texture page.</div>
      )}
    </div>
  )
}

function Tab({
  on,
  disabled,
  title,
  onClick,
  children,
}: {
  on: boolean
  disabled?: boolean
  title?: string
  onClick: () => void
  children: ReactNode
}) {
  return (
    <button
      title={title}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        'h-6 px-2 rounded text-[11px] font-medium border transition-colors cursor-pointer whitespace-nowrap shrink-0 disabled:cursor-default disabled:opacity-35',
        on ? 'bg-primary text-primary-foreground border-primary' : 'bg-stage border-stage-border text-stage-muted hover:text-stage-foreground',
      )}
    >
      {children}
    </button>
  )
}

function toggled(old: Set<number>, keys: number[], on: boolean): Set<number> {
  const next = new Set(old)
  for (const k of keys) {
    if (on) next.add(k)
    else next.delete(k)
  }
  return next
}
