import { Info, LoaderCircle, Play, Search, X } from 'lucide-react'
import { forwardRef, useImperativeHandle, useMemo, useRef, useState } from 'react'
import { Badge } from '../components/ui/badge'
import { Segmented } from '../components/ui/segmented'
import { VirtualList } from '../components/ui/virtual'
import type { Row, TabMeta } from '../lib/api'
import { tabIcon, type RailMode } from '../lib/tabs'
import { clickKeepsKeys, cn } from '../lib/utils'

export interface ItemListHandle {
  focusSearch: () => void
  /** Move the selection by `delta` rows of the FILTERED list. */
  step: (delta: number) => void
}

/**
 * A row's height: its title, sub-line and badge fit in 40 px, the badge
 * and the discs that hold it (where they are not the list's usual ones) at
 * its right; a list whose titles wrap gives them two lines.
 */
function rowHeight(rows: Row[] | null): number {
  const wrap = rows?.some((r) => r.wrap) ?? false
  const sub = rows?.some((r) => r.sub) ?? false
  return wrap ? 12 + 32 + (sub ? 14 : 0) : 40
}

/** The discs holding a row, as one string: its versions' discs apart. */
function discsOf(r: Row): string {
  return r.versions ? r.versions.map((t) => t.join('·')).join(' | ') : r.tags.join('·')
}

/** The discs most of a list's entries are on (each version's, where they
 *  differ between discs): said once for the list, and only an entry on
 *  others says which. */
function usualDiscs(rows: Row[] | null): Row | null {
  const counts = new Map<string, { n: number; row: Row }>()
  for (const r of rows ?? []) {
    if (r.empty) continue
    const k = discsOf(r)
    const c = counts.get(k)
    if (c) c.n++
    else counts.set(k, { n: 1, row: r })
  }
  let best: { n: number; row: Row } | null = null
  for (const c of counts.values()) if (!best || c.n > best.n) best = c
  return best?.row ?? null
}

/** A row as the rail's mode words it: Fan mode's plain words where the
 *  tab gives them. */
function worded(r: Row, fan: boolean): { title: string; sub: string; plain: boolean } {
  if (!fan || !r.fan) return { title: r.title, sub: r.sub, plain: false }
  return { title: r.fan.title ?? r.title, sub: r.fan.sub ?? r.sub, plain: r.fan.sub !== undefined }
}

/**
 * The tab's items. Filtering is a case-insensitive substring match on the
 * provider's full label, so a resource number, a file name or an address
 * all work.
 */
export const ItemList = forwardRef<
  ItemListHandle,
  {
    tab: TabMeta
    view: string | null
    rows: Row[] | null
    loading: boolean
    error: string | null
    selected: number | null
    onView: (v: string) => void
    onSelect: (index: number) => void
    /** Keyboard browsing: the row moves now, the decode may wait. */
    onStep: (index: number) => void
    onActivate: (index: number) => void
    onAbout: () => void
    /** Fan mode words a row as its tab says (Row.fan). */
    railMode: RailMode
  }
>(function ItemList({ tab, view, rows, loading, error, selected, onView, onSelect, onStep, onActivate, onAbout, railMode }, ref) {
  const [query, setQuery] = useState('')
  const searchRef = useRef<HTMLInputElement>(null)
  const Icon = tabIcon(tab.key)

  const fan = railMode === 'fan'
  const shown = useMemo(() => {
    const all = (rows ?? []).map((r, i) => ({ r, i }))
    const q = query.trim().toLowerCase()
    const has = (r: Row) =>
      [r.label, r.title, r.fan?.title ?? '', r.fan?.sub ?? ''].some((t) => t.toLowerCase().includes(q))
    return q ? all.filter(({ r }) => has(r)) : all
  }, [rows, query])

  const at = shown.findIndex((s) => s.i === selected)

  // Rows that name a group come under its heading, where the group changes.
  const listed = useMemo<Listed[]>(() => {
    if (!shown.some(({ r }) => r.group)) return shown
    const counts = new Map<string, number>()
    for (const { r } of shown) counts.set(r.group ?? '', (counts.get(r.group ?? '') ?? 0) + 1)
    const out: Listed[] = []
    let last: string | null = null
    for (const s of shown) {
      const g = s.r.group ?? ''
      if (g !== last) {
        out.push({ head: g, note: s.r.groupNote, count: counts.get(g) ?? 0 })
        last = g
      }
      out.push(s)
    }
    return out
  }, [shown])
  const atListed = listed.findIndex((e) => 'r' in e && e.i === selected)

  useImperativeHandle(
    ref,
    () => ({
      focusSearch: () => searchRef.current?.focus(),
      step: (delta) => {
        if (!shown.length) return
        const next = at < 0 ? (delta > 0 ? 0 : shown.length - 1) : Math.max(0, Math.min(shown.length - 1, at + delta))
        onStep(shown[next].i)
      },
    }),
    [shown, at, onStep],
  )

  const tagged = tab.discs.length > 1
  const rowH = useMemo(() => rowHeight(rows), [rows])
  const total = rows?.length ?? 0
  const real = rows?.filter((r) => !r.empty).length ?? 0
  // the discs most entries are on, said once; an entry on others says so
  const usual = useMemo(() => (tagged ? usualDiscs(rows) : null), [rows, tagged])
  const usualKey = usual ? discsOf(usual) : null
  const odd = useMemo(() => (rows ?? []).filter((r) => !r.empty && discsOf(r) !== usualKey).length, [rows, usualKey])

  return (
    <aside className="w-72 shrink-0 border-r border-border bg-card flex flex-col overflow-hidden">
      <div className="p-3 space-y-2 border-b border-border">
        <div className="flex items-center gap-2">
          <Icon className="w-4 h-4 text-primary shrink-0" />
          <h2 className="text-sm font-semibold truncate flex-1">{tab.name}</h2>
          {loading && <LoaderCircle className="w-3.5 h-3.5 text-muted-foreground animate-spin" />}
          <span className="text-[11px] font-mono text-muted-foreground">{real.toLocaleString()}</span>
          <button className="text-muted-foreground hover:text-primary cursor-pointer" title="About this tab" onClick={onAbout}>
            <Info className="w-3.5 h-3.5" />
          </button>
        </div>
        {tab.views.length > 0 && (
          <Segmented value={view ?? tab.views[0]} onChange={onView} options={tab.views.map((v) => ({ value: v, label: v }))} />
        )}
        {usual && (
          <div className="flex items-center gap-1.5 min-w-0 text-[10px] text-muted-foreground" title={odd ? `${odd} of ${real} entries are on other discs: those say which` : undefined}>
            <span className="shrink-0">{usual.versions ? 'Versions' : 'On'}</span>
            <span className="shrink-0 flex">
              <Tags row={usual} />
            </span>
            <span className="truncate">{odd ? 'unless an entry says otherwise' : real === 1 ? '' : 'every entry'}</span>
          </div>
        )}
        <div className="flex items-center gap-2 h-8 rounded-md border border-input px-2 bg-background focus-within:border-primary">
          <Search className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
          <input
            ref={searchRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Escape') {
                setQuery('')
                e.currentTarget.blur()
              } else if (e.key === 'ArrowDown' || e.key === 'Enter') {
                e.preventDefault()
                e.currentTarget.blur()
                if (shown.length && at < 0) onSelect(shown[0].i)
              }
            }}
            placeholder="Filter (/)"
            className="flex-1 min-w-0 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
          />
          {query && (
            <button className="text-muted-foreground hover:text-foreground cursor-pointer" onClick={() => setQuery('')} title="Clear">
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>
      {error ? (
        <p className="p-4 text-xs text-destructive break-words">{error}</p>
      ) : rows === null ? (
        <div className="flex-1 p-4">
          {loading && (
            <p className="text-xs text-muted-foreground flex items-center gap-2">
              <LoaderCircle className="w-3.5 h-3.5 animate-spin text-primary" /> Listing {tab.name.toLowerCase()}…
            </p>
          )}
        </div>
      ) : (
        <VirtualList
          items={listed}
          rowHeight={rowH}
          scrollTo={atListed >= 0 ? atListed : null}
          empty={<p className="p-4 text-xs text-muted-foreground">{total ? 'Nothing matches the filter.' : 'No entries.'}</p>}
          render={(e) =>
            'r' in e ? (
              <ItemRow
                row={e.r}
                fan={fan}
                tagged={tagged && discsOf(e.r) !== usualKey}
                height={rowH}
                active={e.i === selected}
                onClick={() => onSelect(e.i)}
                onDoubleClick={() => onActivate(e.i)}
              />
            ) : (
              <GroupHead name={e.head} note={e.note} count={e.count} height={rowH} />
            )
          }
        />
      )}
      <div className="px-3 py-1.5 border-t border-border text-[10px] text-muted-foreground font-mono flex justify-between">
        <span>{shown.length !== total ? `${shown.length.toLocaleString()} of ${total.toLocaleString()}` : `${total.toLocaleString()} ${total === 1 ? 'entry' : 'entries'}`}</span>
        <span>↑↓ to browse</span>
      </div>
    </aside>
  )
})

/** A row of the list, or a group's heading over its rows. */
type Listed = { r: Row; i: number } | { head: string; note?: string; count: number }

function GroupHead({ name, note, count, height }: { name: string; note?: string; count: number; height: number }) {
  return (
    <div
      style={{ height }}
      title={note}
      className="px-3 pb-1.5 flex items-end gap-2 border-b border-border bg-muted/50 text-[10px] uppercase tracking-wide font-semibold text-muted-foreground"
    >
      <span className="truncate">{name || 'Other'}</span>
      <span className="font-mono font-normal normal-case">{count}</span>
    </div>
  )
}

function ItemRow({
  row,
  fan,
  tagged,
  height,
  active,
  onClick,
  onDoubleClick,
}: {
  row: Row
  /** Fan mode: the row's plain words, where its tab gives them. */
  fan: boolean
  /** The entry is not on the list's usual discs: say which hold it. */
  tagged: boolean
  height: number
  active: boolean
  onClick: () => void
  onDoubleClick: () => void
}) {
  const tags = tagged && !row.empty
  const badge = row.badge && <Badge tone={row.tone ?? 'muted'}>{row.badge}</Badge>
  const { title, sub, plain } = worded(row, fan)
  return (
    <button
      onMouseDown={clickKeepsKeys}
      onClick={onClick}
      onDoubleClick={onDoubleClick}
      style={{ paddingLeft: 12 + (row.indent ?? 0) * 12, height }}
      className={cn(
        'w-full text-left pr-3 border-b border-border/60 flex items-center gap-2 cursor-pointer transition-colors',
        active ? 'bg-accent border-l-[3px] border-l-primary' : 'hover:bg-muted',
      )}
    >
      {row.action && <Play className="w-3.5 h-3.5 text-primary shrink-0" />}
      <span className="flex-1 min-w-0">
        <span
          title={row.wrap ? title : undefined}
          className={cn(
            'block text-xs',
            row.wrap ? 'line-clamp-2 leading-4 break-words' : 'truncate',
            row.mono && 'font-mono',
            row.empty ? 'italic text-muted-foreground' : 'font-medium',
            row.action && 'text-primary',
            active && !row.empty && 'text-primary',
          )}
        >
          {title}
        </span>
        {sub && <span className={cn('block text-[10px] leading-[14px] text-muted-foreground truncate', !plain && 'font-mono')}>{sub}</span>}
      </span>
      {row.progress !== undefined && (
        <span className="w-12 h-1 rounded-full bg-secondary overflow-hidden shrink-0" title={`${Math.round(row.progress * 100)}%`}>
          <span className="block h-full bg-ok" style={{ width: `${Math.min(100, row.progress * 100)}%` }} />
        </span>
      )}
      {(badge || tags) && (
        <span className="shrink-0 max-w-[45%] flex flex-col items-end gap-0.5 min-w-0">
          {badge}
          {tags && <Tags row={row} />}
        </span>
      )}
    </button>
  )
}

/** The discs holding a row; a row with versions shows each version's discs apart. */
function Tags({ row }: { row: Row }) {
  const groups = row.versions ?? [row.tags]
  const title = row.versions
    ? `Different on ${row.versions.map((t) => t.join(' · ')).join(' and ')}`
    : `On ${row.tags.join(', ')}`
  return (
    <span className="flex items-center gap-0.5 min-w-0 overflow-hidden" title={title}>
      {groups.map((tags, i) => (
        <span
          key={i}
          className={cn(
            'h-4 px-1 rounded text-[9px] font-semibold leading-4 whitespace-nowrap',
            row.versions ? 'bg-warn-soft text-warn' : 'bg-accent text-primary',
          )}
        >
          {tags.join('·')}
        </span>
      ))}
    </span>
  )
}
