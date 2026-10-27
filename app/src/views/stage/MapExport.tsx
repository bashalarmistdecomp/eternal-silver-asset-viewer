import { useRef, useState } from 'react'
import { Button } from '../../components/ui/button'
import { Dialog } from '../../components/ui/dialog'
import { Segmented } from '../../components/ui/segmented'
import { toast } from '../../components/ui/toast'
import { api, type FieldReach, type Layer } from '../../lib/api'
import { blobUrl } from '../../lib/backend'
import { useStored } from '../../lib/hooks'
import { cn } from '../../lib/utils'

/** Which parts of the map a picture draws. */
export interface Parts {
  back: boolean
  tiles: boolean
  roofs: boolean
  sprites: boolean
  /** In game: black where the camera never shows. */
  mask: boolean
}

type Box = [number, number, number, number]
type What = 'shown' | 'areas' | 'layers' | 'tileset'
type Job = { name: string; make: () => Promise<Blob> }

/**
 * A map's pictures, saved in its folder under the disc's exports: the map
 * as shown, each camera area, its layers apart, its tileset. The app draws
 * them at 1x (the map at the moment on screen); the backend blows them up
 * to the scale chosen, each pixel a block.
 */
export function MapExport({
  title,
  inGame,
  reach,
  shown,
  hasBack,
  size,
  tileset,
  draw,
  save,
  onClose,
}: {
  title: string
  inGame: boolean
  reach: FieldReach | null
  /** The parts on screen. */
  shown: Parts
  hasBack: boolean
  size: { w: number; h: number }
  /** The tileset's pages through their CLUTs (the server's pictures). */
  tileset: Layer[]
  /** The whole plane at the moment shown, drawing `parts`. */
  draw: (parts: Parts) => HTMLCanvasElement
  /** Save a PNG under the map's exports folder: its path. */
  save: (name: string, png: Blob, scale: number) => Promise<string>
  onClose: () => void
}) {
  const [picks, setPicks] = useStored<What[]>('map.export.what', ['shown'])
  const [scale, setScale] = useStored('map.export.scale', 1)
  const [busy, setBusy] = useState<{ done: number; total: number } | null>(null)
  const cancelled = useRef(false)
  const areas = reach?.areas ?? []
  const available = (w: What) => (w === 'areas' ? areas.length > 0 : w === 'tileset' ? tileset.length > 0 : true)
  const on = (w: What) => picks.includes(w) && available(w)
  const toggle = (w: What) => setPicks((p) => (p.includes(w) ? p.filter((x) => x !== w) : [...p, w]))
  const layerCount = hasBack ? 3 : 2

  const jobs = (): Job[] => {
    const planes = new Map<string, HTMLCanvasElement>()
    const plane = (parts: Parts) => {
      const key = JSON.stringify(parts)
      if (!planes.has(key)) planes.set(key, draw(parts))
      return planes.get(key)!
    }
    const whole: Box = [0, 0, size.w, size.h]
    const out: Job[] = []
    if (on('shown'))
      out.push({
        name: inGame ? 'map-in-game' : 'map-raw',
        make: () => cut(plane({ ...shown, mask: inGame }), inGame && reach ? reach.bbox : whole),
      })
    if (on('areas')) areas.forEach((a, i) => out.push({ name: `area-${String(i + 1).padStart(2, '0')}`, make: () => cut(plane({ ...shown, mask: true }), a) }))
    if (on('layers')) {
      const none = { back: false, tiles: false, roofs: false, sprites: false, mask: false }
      if (hasBack) out.push({ name: 'layer-back', make: () => cut(plane({ ...none, back: true }), whole) })
      out.push({ name: 'layer-tiles', make: () => cut(plane({ ...none, tiles: true }), whole) })
      out.push({ name: 'layer-sprites', make: () => cut(plane({ ...none, sprites: true }), whole) })
    }
    if (on('tileset'))
      tileset.forEach((l) =>
        out.push({
          name: `tileset-${l.label.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')}`,
          make: async () => {
            const res = await fetch(blobUrl(l.blob, 'png'))
            if (!res.ok) throw new Error(`the tileset page ${l.label} did not load`)
            return res.blob()
          },
        }),
      )
    return out
  }

  const run = async () => {
    const list = jobs()
    if (!list.length) return
    cancelled.current = false
    const paths: string[] = []
    try {
      for (const [i, job] of list.entries()) {
        if (cancelled.current) break
        setBusy({ done: i, total: list.length })
        await new Promise((ok) => requestAnimationFrame(() => ok(null)))
        const png = await job.make()
        paths.push(await save(scale > 1 ? `${job.name}-${scale}x` : job.name, png, scale))
      }
    } catch (e) {
      toast({ tone: 'error', title: 'Export failed', body: e instanceof Error ? e.message : String(e) })
    }
    setBusy(null)
    if (!paths.length) return
    onClose()
    const folder = paths[0].replace(/[\\/][^\\/]*$/, '')
    toast({
      tone: 'ok',
      title: `Exported ${paths.length} picture${paths.length === 1 ? '' : 's'}`,
      body: folder,
      action: { label: 'Show in folder', run: () => void api.reveal(paths[0]) },
    })
  }

  const option = (w: What, label: string, note: string, count: number) => {
    const ok = available(w)
    return (
      <label
        className={cn(
          'flex items-start gap-2.5 rounded-md border px-3 py-2',
          on(w) ? 'border-primary bg-primary/5' : 'border-border',
          ok && !busy ? 'cursor-pointer' : 'opacity-50 cursor-not-allowed',
        )}
      >
        <input type="checkbox" className="mt-0.5 accent-primary" checked={on(w)} disabled={!ok || !!busy} onChange={() => toggle(w)} />
        <span className="flex-1 space-y-0.5">
          <span className="block text-xs font-medium">{label}</span>
          <span className="block text-[11px] text-muted-foreground leading-snug">{note}</span>
        </span>
        <span className="text-[11px] font-mono text-muted-foreground">{ok ? count : '—'}</span>
      </label>
    )
  }

  const total = (on('shown') ? 1 : 0) + (on('areas') ? areas.length : 0) + (on('layers') ? layerCount : 0) + (on('tileset') ? tileset.length : 0)

  return (
    <Dialog
      title={`Export ${title}`}
      onClose={() => {
        cancelled.current = true
        onClose()
      }}
      className="w-[480px]"
    >
      <div className="space-y-2">
        {option(
          'shown',
          'The map as shown',
          `${inGame ? 'In game: what a player sees, the rest black' : 'Raw: the whole plane'}, with the layers, story flags and moment on screen.`,
          1,
        )}
        {option(
          'areas',
          'Each area',
          areas.length ? 'One picture per camera area (a town, each house), cut to what the camera shows there.' : 'No way in reaches this map: it has no camera areas.',
          areas.length,
        )}
        {option(
          'layers',
          'Layers apart',
          `${hasBack ? 'The second layer, the tiles' : 'The tiles'} and the sprites, each on its own over transparency, the whole plane.`,
          layerCount,
        )}
        {option('tileset', 'Tileset', 'Each texture page the map loads, through each CLUT that draws it.', tileset.length)}
      </div>
      <div className="mt-3 flex items-center gap-3">
        <span className="text-[11px] text-muted-foreground">Scale</span>
        <Segmented
          value={scale}
          onChange={setScale}
          options={[1, 2, 4].map((s) => ({ value: s, label: `${s}×`, disabled: !!busy }))}
          className="flex-nowrap"
        />
      </div>
      <p className="mt-3 text-[11px] text-muted-foreground">
        {busy ? `Saving ${busy.done + 1} of ${busy.total}…` : "Saved in the map's own folder under the disc's exports."}
      </p>
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={() => (busy ? (cancelled.current = true) : onClose())}>
          {busy ? 'Stop' : 'Cancel'}
        </Button>
        <Button size="sm" disabled={!!busy || total === 0} onClick={() => void run()}>
          {busy ? 'Exporting…' : `Export ${total} picture${total === 1 ? '' : 's'}`}
        </Button>
      </div>
    </Dialog>
  )
}

function cut(src: HTMLCanvasElement, [x0, y0, x1, y1]: Box): Promise<Blob> {
  const c = document.createElement('canvas')
  c.width = x1 - x0
  c.height = y1 - y0
  c.getContext('2d')!.drawImage(src, x0, y0, c.width, c.height, 0, 0, c.width, c.height)
  return new Promise((ok, no) => c.toBlob((b) => (b ? ok(b) : no(new Error('the picture could not be made'))), 'image/png'))
}
