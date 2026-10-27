import { BadgeCheck, Disc3, FolderCog, FolderInput, HardDrive, Info, LoaderCircle, Plus, RefreshCw, TriangleAlert } from 'lucide-react'
import { Badge } from '../components/ui/badge'
import { Button } from '../components/ui/button'
import logo from '../brand/asset-viewer-logo.png'
import type { DiscIndex, DiscRow, Library, LibraryDisc, PoolRow, Slot, SlotDisc } from '../lib/api'
import { inTauri } from '../lib/backend'
import { PARTIAL } from '../lib/tabs'
import { cn, fmtBytes, plural } from '../lib/utils'

/**
 * One slot per game: Lunar 1 holds both US discs, the Japanese discs, the
 * demo and the making-of disc, and opens as one game. Each slot lists every
 * disc gamedb knows of it — extracted, waiting in the library's discs/
 * folder, or not added yet — and adds a disc where it is missing.
 */
export function LibraryHome({
  library,
  opening,
  onOpen,
  onAdd,
  onAddFolder,
  onExtract,
  onReextract,
  onReextractGame,
  onChooseFolder,
  onRefresh,
}: {
  library: Library
  /** The slot being opened, if one is: every Open waits for it. */
  opening: string | null
  /** Open a slot as one game. */
  onOpen: (key: string) => void
  /** Choose a disc image to add (it joins the slot it belongs to). */
  onAdd: () => void
  /** Choose a folder: every disc image in it the library does not hold yet is added. */
  onAddFolder: () => void
  /** Extract an image already in the library's discs/ folder. */
  onExtract: (path: string) => void
  onReextract: (disc: DiscRow) => void
  /** Extract every disc of a slot again. */
  onReextractGame: (slot: Slot) => void
  /** Use another library folder. */
  onChooseFolder: () => void
  onRefresh: () => void
}) {
  const folder = library.folder
  const slots = [...library.games, ...library.others]
  const extracted = slots.reduce((n, g) => n + g.present, 0)
  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="max-w-6xl mx-auto space-y-6">
        <header className="flex justify-center">
          {/* drawn at 1x by tools/brand/, shown at 2x, each pixel a square */}
          <img
            src={logo}
            alt="Eternal Silver Asset Viewer"
            width={432}
            height={206}
            draggable={false}
            className="max-w-full h-auto select-none [image-rendering:pixelated]"
          />
        </header>
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h1 className="text-lg font-semibold">Library</h1>
            <p className="text-xs text-muted-foreground font-mono break-all flex items-center gap-1.5">
              <HardDrive className="w-3 h-3 shrink-0" />
              {folder.path}
              {!folder.exists && <Badge tone="muted">created on the first extraction</Badge>}
            </p>
            <p className="text-xs text-muted-foreground mt-1">
              {plural(library.games.length, 'game')} · {plural(extracted, 'disc')} extracted
            </p>
          </div>
          <div className="flex gap-2 shrink-0">
            <Button size="sm" variant="outline" onClick={onAddFolder} title="Choose a folder: every disc image in it and its subfolders that the library does not hold yet is extracted">
              <FolderInput className="w-3.5 h-3.5" /> Add a folder…
            </Button>
            <Button size="sm" variant="ghost" onClick={onRefresh} title="Look again">
              <RefreshCw className="w-3.5 h-3.5" />
            </Button>
            {inTauri && (
              <Button size="sm" variant="ghost" onClick={onChooseFolder} title="Use another library folder">
                <FolderCog className="w-3.5 h-3.5" />
              </Button>
            )}
          </div>
        </div>

        <div className="grid gap-4 items-start" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(420px, 1fr))' }}>
          {library.games.map((g) => (
            <SlotCard key={g.key} slot={g} opening={opening} onOpen={() => onOpen(g.key)} onAdd={onAdd} onExtract={onExtract} onReextract={onReextract} onReextractAll={() => onReextractGame(g)} />
          ))}
        </div>

        {library.others.length > 0 && (
          <div className="space-y-2">
            <h2 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Other discs</h2>
            <div className="grid gap-4 items-start" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(420px, 1fr))' }}>
              {library.others.map((g) => (
                <SlotCard key={g.key} slot={g} opening={opening} onOpen={() => onOpen(g.key)} onAdd={onAdd} onExtract={onExtract} onReextract={onReextract} onReextractAll={() => onReextractGame(g)} />
              ))}
            </div>
          </div>
        )}

        {library.unsorted.length > 0 && <Unsorted rows={library.unsorted} onExtract={onExtract} />}
      </div>
      {/* the app's version (docs/development.md, "Versions"), in the window's corner, the list scrolling under it */}
      <p className="fixed bottom-1.5 right-4 rounded px-1.5 bg-background/80 text-[11px] font-mono text-muted-foreground">
        v{__APP_VERSION__}
      </p>
    </div>
  )
}

function SlotCard({
  slot,
  opening,
  onOpen,
  onAdd,
  onExtract,
  onReextract,
  onReextractAll,
}: {
  slot: Slot
  opening: string | null
  onOpen: () => void
  onAdd: () => void
  onExtract: (path: string) => void
  onReextract: (disc: DiscRow) => void
  onReextractAll: () => void
}) {
  const ready = slot.present > 0
  return (
    <section className="rounded-lg border border-border bg-card shadow-sm overflow-hidden flex flex-col">
      <div className="p-4 pb-3 border-b border-border/70 flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <h2 className="font-semibold leading-tight">{slot.title}</h2>
          <p className="text-[11px] text-muted-foreground mt-1">
            {slot.present} of {plural(slot.discs.length, 'disc')} extracted
            {ready && ' · opens with all of them'}
          </p>
        </div>
        {ready && (
          <Button size="sm" variant="ghost" className="h-7 px-2 shrink-0 text-muted-foreground" onClick={onReextractAll} title="Extract every disc of it again, replacing their dumps">
            <RefreshCw className="w-3.5 h-3.5" /> Re-extract all
          </Button>
        )}
        <Button
          size="sm"
          className="h-7 px-3 shrink-0"
          disabled={!ready || opening !== null}
          onClick={onOpen}
          title={ready ? 'Open the game: every extracted disc of it' : 'Add a disc first'}
        >
          {opening === slot.key && <LoaderCircle className="w-3.5 h-3.5 animate-spin" />} Open
        </Button>
      </div>
      {slot.partial && (
        <div className="px-4 py-2.5 border-b border-border/70 bg-info-soft text-xs leading-relaxed flex items-start gap-2">
          <Info className="w-3.5 h-3.5 mt-0.5 text-info shrink-0" />
          <p>
            <span className="font-semibold">Not fully supported yet.</span> {PARTIAL}
          </p>
        </div>
      )}
      <div className="divide-y divide-border/70 flex-1">
        {slot.discs.map((d) =>
          d.state === 'present' && d.disc ? (
            <PresentDisc key={d.serial} slotDisc={d} disc={d.disc} onOpen={onOpen} onReextract={() => onReextract(d.disc!)} />
          ) : (
            <AbsentDisc key={d.serial} disc={d} onAdd={onAdd} onExtract={onExtract} />
          ),
        )}
      </div>
    </section>
  )
}

function Tag({ children, dim }: { children: string; dim?: boolean }) {
  return (
    <span
      className={cn(
        'w-[74px] shrink-0 h-6 rounded-md text-[11px] font-semibold flex items-center justify-center',
        dim ? 'border border-dashed border-border text-muted-foreground' : 'bg-accent text-primary',
      )}
    >
      {children}
    </span>
  )
}

function PresentDisc({ slotDisc, disc: d, onOpen, onReextract }: { slotDisc: SlotDisc; disc: LibraryDisc; onOpen: () => void; onReextract: () => void }) {
  const bits = [d.discId, d.volumeId, d.readable ? `${d.files} files, ${fmtBytes(d.bytes)}` : 'dump unreadable'].filter(Boolean)
  return (
    <div className="group px-4 py-2.5 flex items-center gap-3 hover:bg-muted/60" onDoubleClick={onOpen}>
      <Tag>{slotDisc.tag}</Tag>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-xs font-medium truncate">{d.label}</span>
          {d.identifiedBy === 'checksum' ? (
            <span title="Identified by checksum: the data track's sha256 is in gamedb's table" className="text-ok shrink-0">
              <BadgeCheck className="w-3.5 h-3.5" />
            </span>
          ) : (
            d.warning && (
              <Badge tone={d.warning.tone === 'danger' ? 'danger' : 'warn'}>
                <TriangleAlert className="w-3 h-3" /> {d.warning.text}
              </Badge>
            )
          )}
        </div>
        <p className="text-[11px] font-mono text-muted-foreground truncate" title={bits.join(' · ')}>
          {bits.join(' · ')}
        </p>
        {!d.source && <p className="text-[10px] text-warn mt-0.5">disc image not found — CD audio, movie sound and re-extraction need it</p>}
        <Indexing index={d.index} />
      </div>
      <Button
        size="sm"
        variant="ghost"
        className="h-7 opacity-0 group-hover:opacity-100 focus:opacity-100 shrink-0"
        onClick={onReextract}
        title="Extract this disc again, replacing the dump"
      >
        <RefreshCw className="w-3.5 h-3.5" />
      </Button>
    </div>
  )
}

/**
 * The disc's index being made (or waiting its turn): what its tabs list
 * and its links, kept so the game opens without reading the disc whole.
 * The game opens meanwhile, read from the disc's files.
 */
function Indexing({ index }: { index: DiscIndex }) {
  if (index.state === 'queued') {
    return <p className="text-[10px] text-muted-foreground mt-0.5">waiting to be indexed · opens meanwhile, read from its files</p>
  }
  if (index.state !== 'making') return null
  const pct = index.total ? Math.min(100, (100 * (index.current ?? 0)) / index.total) : null
  return (
    <div className="mt-1 flex items-center gap-2 min-w-0" title="Opens meanwhile, read from its files">
      <LoaderCircle className="w-3 h-3 animate-spin text-primary shrink-0" />
      <span className="text-[10px] text-muted-foreground truncate">{index.message || 'Indexing…'}</span>
      <div className="h-1 w-20 bg-secondary rounded-full overflow-hidden shrink-0">
        <div className="h-full bg-primary transition-[width]" style={{ width: `${pct ?? 8}%` }} />
      </div>
    </div>
  )
}

function AbsentDisc({ disc: d, onAdd, onExtract }: { disc: SlotDisc; onAdd: () => void; onExtract: (path: string) => void }) {
  const waiting = d.state === 'in-folder' && d.pool
  return (
    <div className="px-4 py-2.5 flex items-center gap-3">
      <Tag dim>{d.tag}</Tag>
      <div className="flex-1 min-w-0">
        <p className="text-xs text-muted-foreground truncate">{d.label}</p>
        <p className="text-[11px] text-muted-foreground/80 truncate" title={waiting ? d.pool!.path : undefined}>
          {waiting ? `in the library's discs/ folder · ${fmtBytes(d.pool!.bytes)}` : 'not added yet'}
        </p>
      </div>
      {waiting ? (
        <Button size="sm" variant="outline" className="h-7 shrink-0" onClick={() => onExtract(d.pool!.path)} title={d.pool!.path}>
          <FolderInput className="w-3.5 h-3.5" /> Add
        </Button>
      ) : (
        <Button size="sm" variant="outline" className="h-7 shrink-0" onClick={onAdd} title="Choose this disc's image (.cue, .iso or .bin)">
          <Plus className="w-3.5 h-3.5" /> Add…
        </Button>
      )}
    </div>
  )
}

function Unsorted({ rows, onExtract }: { rows: PoolRow[]; onExtract: (path: string) => void }) {
  return (
    <div className="space-y-2">
      <h2 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">In the library's discs/, not identified yet</h2>
      <div className="flex flex-wrap gap-2">
        {rows.map((r) => (
          <div key={r.path} className="rounded-lg border border-dashed border-border bg-card px-3 py-2 flex items-center gap-3 max-w-md">
            <Disc3 className="w-4 h-4 text-muted-foreground shrink-0" />
            <div className="min-w-0">
              <p className="text-xs font-medium truncate">{r.title}</p>
              <p className="text-[10px] font-mono text-muted-foreground truncate" title={r.path}>
                {fmtBytes(r.bytes)}
              </p>
            </div>
            <Button size="sm" variant="outline" className="h-7 shrink-0" onClick={() => onExtract(r.path)} title="Extract it: it joins the game it belongs to">
              Add
            </Button>
          </div>
        ))}
      </div>
    </div>
  )
}
