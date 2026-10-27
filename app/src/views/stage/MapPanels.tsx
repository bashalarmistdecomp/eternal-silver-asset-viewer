import { ChevronDown, ChevronRight, Crosshair, IdCard, Play, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import type { BgChangeRow, FieldObject, FieldScene, Ref, SceneActor } from '../../lib/api'
import { rowRect, type Rect } from '../../lib/game/bgChange'
import { nav } from '../../lib/nav'
import { cn } from '../../lib/utils'
import { GROUP_TONE, hex } from './mapStyle'

/** A panel along the map's right edge. */
export function Panel({ title, aside, onClose, children }: { title: string; aside?: ReactNode; onClose: () => void; children: ReactNode }) {
  return (
    <aside className="w-80 shrink-0 border-l border-stage-border bg-stage-raised text-stage-foreground flex flex-col min-h-0 selectable">
      <div className="h-10 shrink-0 px-3 border-b border-stage-border flex items-center gap-2">
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-stage-muted flex-1">{title}</h3>
        {aside}
        <button className="text-stage-muted hover:text-white cursor-pointer" title="Close" onClick={onClose}>
          <X className="w-4 h-4" />
        </button>
      </div>
      {children}
    </aside>
  )
}

function Switch({ on, title, onClick }: { on: boolean; title: string; onClick: () => void }) {
  return (
    <button
      role="switch"
      aria-checked={on}
      title={title}
      onClick={onClick}
      className={cn('relative w-7 h-4 rounded-full shrink-0 cursor-pointer transition-colors', on ? 'bg-primary' : 'bg-white/15 hover:bg-white/25')}
    >
      <span className={cn('absolute top-0.5 w-3 h-3 rounded-full bg-white transition-all', on ? 'left-3.5' : 'left-0.5')} />
    </button>
  )
}

function IconButton({ title, onClick, children }: { title: string; onClick: () => void; children: ReactNode }) {
  return (
    <button title={title} onClick={onClick} className="w-6 h-6 rounded flex items-center justify-center text-stage-muted hover:text-white hover:bg-white/10 cursor-pointer shrink-0">
      {children}
    </button>
  )
}

/** Every object the set makes, along the map's right edge. An entry picks
 *  its object on the map; an object picked on the map lights its entry. A
 *  story flag's badge sets or clears the flag. */
export function ObjectsPanel({
  objects,
  sel,
  bits,
  disc,
  onPick,
  onBit,
  onClose,
}: {
  objects: FieldObject[]
  sel: number
  bits: Set<number>
  /** The disc the map is read from, for the objects' cards. */
  disc?: string
  onPick: (actor: number) => void
  onBit: (bit: number, on: boolean) => void
  onClose: () => void
}) {
  const list = useRef<HTMLDivElement>(null)
  useEffect(() => {
    list.current?.querySelector('[data-sel="true"]')?.scrollIntoView({ block: 'nearest' })
  }, [sel])
  const counts = new Map<string, number>()
  for (const o of objects) counts.set(o.group, (counts.get(o.group) ?? 0) + 1)
  const badge = (bit: number, text: string, why: string) => (
    <button
      onClick={(e) => {
        e.stopPropagation()
        onBit(bit, !bits.has(bit))
      }}
      title={`${why} (story flag ${bit}, ${hex(bit, 3)}) — click to ${bits.has(bit) ? 'clear' : 'set'} it`}
      className={cn(
        'rounded px-1 font-mono text-[10px] cursor-pointer',
        bits.has(bit) ? 'bg-primary text-primary-foreground' : 'bg-white/10 text-stage-foreground/80 hover:bg-white/20',
      )}
    >
      {text} story flag {bit}
    </button>
  )
  return (
    <Panel title="Objects" onClose={onClose}>
      <div className="px-3 py-2 border-b border-stage-border flex flex-wrap gap-x-3 gap-y-1 text-[10px]">
        {[...counts].map(([g, n]) => (
          <span key={g} className={GROUP_TONE[g]}>
            {g} <span className="font-mono text-stage-muted">{n}</span>
          </span>
        ))}
      </div>
      <div ref={list} className="flex-1 overflow-y-auto">
        {objects.map((o, i) => {
          const picked = o.actor !== null && o.actor === sel
          return (
            <div
              key={i}
              data-sel={picked}
              onClick={() => o.actor !== null && onPick(o.actor)}
              title={o.actor === null ? 'Its sheet draws nothing' : 'Show it on the map'}
              className={cn(
                'px-3 py-1.5 border-b border-stage-border/60',
                o.actor === null ? 'opacity-50' : 'cursor-pointer',
                picked ? 'bg-primary/20' : o.actor !== null && 'hover:bg-white/5',
                o.out !== null && bits.has(o.out) && 'opacity-60',
              )}
            >
              <div className="flex items-baseline gap-2 text-[11px]">
                <span className={cn('font-medium', GROUP_TONE[o.group])}>{o.name}</span>
                {o.kind !== null && <span className="text-stage-muted">object kind {o.kind}</span>}
                <span className="ml-auto font-mono text-stage-muted">
                  {o.x}, {o.y}
                </span>
                {o.ref && disc && (
                  <button
                    title="Open its card"
                    onClick={(e) => {
                      e.stopPropagation()
                      nav.open(o.ref!, disc)
                    }}
                    className="self-center text-stage-muted hover:text-white cursor-pointer"
                  >
                    <IdCard className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>
              <div className="text-[10px] text-stage-muted leading-snug break-words">
                {o.row !== null && `object row ${o.row} · `}
                sprite {hex(o.data)}
                {o.think !== null && ` · think ${hex(o.think)}`} · {o.how}
              </div>
              {(o.out !== null || o.open !== null) && (
                <div className="mt-0.5 flex flex-wrap gap-1">
                  {o.out !== null && badge(o.out, 'gone with', 'MapObjectsInit (0x800655C8) leaves it out while this story flag is set')}
                  {o.open !== null && badge(o.open, 'open with', 'MapObjectInit (0x800656CC) shows the chest open while this story flag is set')}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </Panel>
  )
}

interface Entry {
  key: string
  on: boolean
  toggle: () => void
  name: string
  what: string
  more?: string
  rect?: Rect
  focus?: () => void
  play?: () => void
  /** The story flag, whose card the entry opens. */
  card?: Ref
}

/** The map's story flags and other tile changes, each a switch: a flag set
 *  leaves its tile changes copied, its objects out and its chests open; a
 *  door or other change opened is copied as if started. ▶ plays the copies one
 *  source at a time on the field's clock; a flag's card says what else sets
 *  and checks it. */
export function StoryPanel({
  story,
  actors,
  objects,
  bits,
  doors,
  onBits,
  onDoors,
  onPlay,
  onHover,
  onFocus,
  disc,
  onClose,
}: {
  story: FieldScene['story']
  actors: SceneActor[]
  objects: FieldObject[]
  bits: Set<number>
  doors: Set<number>
  onBits: (bits: number[], on: boolean) => void
  onDoors: (ids: number[], on: boolean) => void
  onPlay: (row: BgChangeRow) => void
  onHover: (rect: Rect | null) => void
  onFocus: (x: number, y: number, actor?: number) => void
  /** The disc the map is read from, for the flags' cards. */
  disc?: string
  onClose: () => void
}) {
  const sections = useMemo(() => {
    const rows = new Map(story.rows.map((r) => [r.id, r]))
    const objOf = new Map(objects.filter((o) => o.actor !== null).map((o) => [o.actor!, o]))
    const rowWhat = (r: BgChangeRow) =>
      `${r.w * 8}×${r.h * 8} at (${r.x * 8}, ${r.y * 8})` +
      (r.sources.length > 1 ? ` · ${r.sources.length} copies ${r.frames} frames apart` : '') +
      (r.sound ? ` · sound ${r.sound}` : '')
    const out: { title: string; note?: string; entries: Entry[] }[] = [
      { title: 'Tile changes', entries: [] },
      { title: 'Chests', entries: [] },
      { title: 'Entities and triggers', entries: [] },
      { title: 'Monsters', entries: [] },
      { title: 'Doors', note: 'Per visit: the map loads them closed again.', entries: [] },
      { title: 'Other changes', note: 'Started by a script, or by nothing found.', entries: [] },
    ]
    for (const b of story.bits) {
      const on = bits.has(b.bit)
      const base = { key: `bit${b.bit}`, on, toggle: () => onBits([b.bit], !on), name: `story flag ${b.bit}`, card: b.ref }
      if (b.rows.length) {
        const rs = b.rows.map((id) => rows.get(id)!).filter(Boolean)
        const first = rs[0]
        const trig = rs.flatMap((r) => r.triggers)
        const more = [
          trig.length ? `set when the party steps on (${trig[0][0]}, ${trig[0][1]})` : '',
          b.maps.length ? `also on ${b.maps.map(([, n]) => n).join(', ')}` : '',
        ]
          .filter(Boolean)
          .join(' · ')
        out[0].entries.push({
          ...base,
          what: `tile change${b.rows.length === 1 ? '' : 's'} ${b.rows.join(', ')} · ${rowWhat(first)}`,
          more: more || undefined,
          rect: rowRect(first),
          focus: () => onFocus(first.x * 8 + first.w * 4, first.y * 8 + first.h * 4),
          play: () => onPlay(first),
        })
        continue
      }
      const actorsOf = [...b.hides, ...b.opens]
      const first = actorsOf[0]
      const at = first !== undefined ? actors[first].track![0] : undefined
      const focus = at ? () => onFocus(at[1], at[2], first) : undefined
      const named = (ids: number[]) => ids.map((i) => objOf.get(i)?.name ?? `object ${i}`).join(', ')
      if (b.opens.length) {
        out[1].entries.push({ ...base, what: `opens ${named(b.opens)}`, focus })
        continue
      }
      const group = objOf.get(b.hides[0])?.group
      out[group === 'chests' ? 1 : group === 'monsters' ? 3 : 2].entries.push({ ...base, what: `leaves out ${named(b.hides)}`, focus })
    }
    for (const r of story.rows) {
      if (r.kind === 'state') continue
      const on = doors.has(r.id)
      out[r.kind === 'door' ? 4 : 5].entries.push({
        key: `row${r.id}`,
        on,
        toggle: () => onDoors([r.id], !on),
        name: `tile change ${r.id}`,
        what: rowWhat(r),
        more: r.triggers.length ? `starts when the party steps on (${r.triggers[0][0]}, ${r.triggers[0][1]})` : undefined,
        rect: rowRect(r),
        focus: () => onFocus(r.x * 8 + r.w * 4, r.y * 8 + r.h * 4),
        play: () => onPlay(r),
      })
    }
    return out.filter((s) => s.entries.length)
  }, [story, actors, objects, bits, doors, onBits, onDoors, onPlay, onFocus])

  const anyOn = bits.size > 0 || doors.size > 0
  return (
    <Panel
      title="Story flags"
      onClose={onClose}
      aside={
        anyOn && (
          <button
            className="text-[10px] text-stage-muted hover:text-white cursor-pointer"
            title="Clear every story flag and close every tile change: the map as it loads"
            onClick={() => {
              onBits([...bits], false)
              onDoors([...doors], false)
            }}
          >
            clear all
          </button>
        )
      }
    >
      <div className="flex-1 overflow-y-auto" onMouseLeave={() => onHover(null)}>
        {sections.length === 0 && <p className="p-3 text-[11px] text-stage-muted">No story flag changes what this map shows, and it has no tile change.</p>}
        {sections.map((s) => (
          <Section key={s.title} title={s.title} note={s.note} entries={s.entries} disc={disc} onHover={onHover} />
        ))}
        <p className="px-3 py-3 text-[10px] leading-relaxed text-stage-muted">
          The paths are played with every story flag clear: a flag that moves a wall or leaves an object out does not re-route the others.
        </p>
      </div>
    </Panel>
  )
}

function Section({ title, note, entries, disc, onHover }: { title: string; note?: string; entries: Entry[]; disc?: string; onHover: (r: Rect | null) => void }) {
  const [open, setOpen] = useState(entries.length <= 12)
  const allOn = entries.every((e) => e.on)
  return (
    <div className="border-b border-stage-border">
      <div className="h-8 px-2 flex items-center gap-1 sticky top-0 bg-stage-raised z-10">
        <button className="flex items-center gap-1 flex-1 min-w-0 text-left cursor-pointer" onClick={() => setOpen((o) => !o)}>
          {open ? <ChevronDown className="w-3.5 h-3.5 text-stage-muted" /> : <ChevronRight className="w-3.5 h-3.5 text-stage-muted" />}
          <span className="text-[11px] font-semibold">{title}</span>
          <span className="font-mono text-[10px] text-stage-muted">{entries.length}</span>
        </button>
        <button
          className="text-[10px] text-stage-muted hover:text-white cursor-pointer px-1"
          title={allOn ? 'Clear them all' : 'Set them all'}
          onClick={() => {
            for (const e of entries) if (e.on === allOn) e.toggle()
          }}
        >
          {allOn ? 'none' : 'all'}
        </button>
      </div>
      {open && note && <p className="px-3 pb-1.5 -mt-1 text-[10px] text-stage-muted">{note}</p>}
      {open &&
        entries.map((e) => (
          <div
            key={e.key}
            className={cn('px-3 py-1.5 flex items-start gap-2 hover:bg-white/5', e.on && 'bg-primary/10')}
            onMouseEnter={() => onHover(e.rect ?? null)}
          >
            <div className="pt-0.5">
              <Switch on={e.on} title={e.on ? 'Clear' : 'Set'} onClick={e.toggle} />
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-[11px] font-mono font-semibold">{e.name}</div>
              <div className="text-[10px] text-stage-muted leading-snug break-words">{e.what}</div>
              {e.more && <div className="text-[10px] text-stage-muted/80 leading-snug break-words">{e.more}</div>}
            </div>
            {e.play && (
              <IconButton title="Play it: one copy per source, on the field's clock" onClick={e.play}>
                <Play className="w-3 h-3" />
              </IconButton>
            )}
            {e.focus && (
              <IconButton title="Show it on the map" onClick={e.focus}>
                <Crosshair className="w-3 h-3" />
              </IconButton>
            )}
            {e.card && disc && (
              <IconButton title="Open its card: what sets, clears and checks it" onClick={() => nav.open(e.card!, disc)}>
                <IdCard className="w-3 h-3" />
              </IconButton>
            )}
          </div>
        ))}
    </div>
  )
}
