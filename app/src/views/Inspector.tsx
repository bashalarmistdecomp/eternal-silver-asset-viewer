import { FolderOpen, IdCard, PanelRightClose, PanelRightOpen, TriangleAlert } from 'lucide-react'
import { Extended } from '../components/Extended'
import { LinkGroups } from '../components/RefLink'
import { Badge } from '../components/ui/badge'
import { api, type LinkGroup, type Result, type Row, type Session, type TabMeta } from '../lib/api'
import { nav } from '../lib/nav'
import { splitAdvanced } from '../lib/refs'
import type { RailMode } from '../lib/tabs'
import { cn, kindTone } from '../lib/utils'
import { SummaryView } from './stage/SummaryView'
import { isPictorial } from './Stage'

type InfoLine = { k: string; v: string } | { line: string } | { warn: string }

/**
 * The providers' info text, laid out. It was written for a 220 px label
 * and reads as `key: value` lines plus free lines; those become rows, and
 * a `source:` line — what kind of bytes the item was decoded from — is
 * shown as a badge.
 */
function parseInfo(info: string): { title: string; lines: InfoLine[] } {
  const raw = info.split('\n').filter((l) => l.trim())
  const lines: InfoLine[] = []
  for (const l of raw.slice(1)) {
    const warn = l.match(/^\s*!\s*(.*)$/)
    const kv = l.match(/^\s*([A-Za-z][\w /().'-]{0,22}):\s+(.+)$/)
    if (warn) lines.push({ warn: warn[1] })
    else if (kv) lines.push({ k: kv[1], v: kv[2] })
    else lines.push({ line: l.trim() })
  }
  return { title: raw[0] ?? '', lines }
}

export function Inspector({
  session,
  tab,
  result,
  row,
  railMode,
  open,
  onToggle,
}: {
  session: Session
  tab: TabMeta
  result: Result | null
  /** The list's row the result is of: Fan mode heads a result that is no
   *  thing of the game (a menu's picture) with its words. */
  row?: Row | null
  railMode: RailMode
  /** Collapsed, it is a strip at the window's right edge that opens it again. */
  open: boolean
  onToggle: () => void
}) {
  if (!open) {
    return (
      <aside className="w-9 shrink-0 border-l border-border bg-card flex flex-col items-center">
        <button className="h-10 w-full flex items-center justify-center text-muted-foreground hover:text-primary cursor-pointer" title="Show the Inspector (I)" onClick={onToggle}>
          <PanelRightOpen className="w-4 h-4" />
        </button>
        <button
          className="flex-1 w-full pt-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground hover:text-primary cursor-pointer [writing-mode:vertical-rl]"
          title="Show the Inspector (I)"
          onClick={onToggle}
        >
          Inspector
        </button>
      </aside>
    )
  }
  return <InspectorPanel session={session} tab={tab} result={result} row={row ?? null} railMode={railMode} onToggle={onToggle} />
}

/**
 * What the selection is, laid out as a card is (docs/taxonomy.md, "The
 * cards"): its title and reference, its links, then the extended info —
 * what the provider says of how it was read, the links to things only
 * Advanced mode has a tab for — folded in Fan mode, open in Advanced.
 */
function InspectorPanel({
  session,
  tab,
  result,
  row,
  railMode,
  onToggle,
}: {
  session: Session
  tab: TabMeta
  result: Result | null
  row: Row | null
  railMode: RailMode
  onToggle: () => void
}) {
  const info = result ? parseInfo(result.info) : null
  // An entry exports to the folder of the disc it came from.
  const exportsDir = result?.exportsDir ?? session.exportsDir
  const pictorial = isPictorial(result)
  const advanced = railMode === 'advanced'
  // A thing of the game is headed by its title and reference; anything
  // else by its info's first line, or in Fan mode by its row's words.
  const named = !!result?.written
  const head = result
    ? named
      ? result.title || result.written!
      : !advanced && row
        ? row.fan?.title || row.title
        : info!.title || result.label
    : ''
  const under = result
    ? named
      ? `${result.written}${advanced && result.hex && result.hex !== result.written ? ` · ${result.hex}` : ''}`
      : !advanced && row
        ? (row.fan?.sub ?? row.sub)
        : info!.title && result.label && info!.title !== result.label.trim()
          ? result.label.trim()
          : ''
    : ''
  // the info's first line, where it says more than the heading does
  const infoTitle = info?.title && info.title !== head && info.title !== result?.written ? info.title : ''
  const links = result?.ref ? (advanced ? { plain: result.links ?? [], advanced: [] } : splitAdvanced(result.links ?? [])) : null
  const extended = !!result && (!!infoTitle || info!.lines.length > 0 || !!links?.advanced.length || (pictorial && (!!result.summary || !!result.text)))
  return (
    <aside className="w-72 shrink-0 border-l border-border bg-card flex flex-col overflow-hidden">
      <div className="h-10 shrink-0 px-3 border-b border-border flex items-center">
        <h2 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground flex-1">Inspector</h2>
        <button className="text-muted-foreground hover:text-primary cursor-pointer" title="Hide the Inspector (I)" onClick={onToggle}>
          <PanelRightClose className="w-4 h-4" />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-3 space-y-4 selectable">
        {!result ? (
          <p className="text-xs text-muted-foreground">
            {advanced
              ? 'Details of the selected entry show here: its size, format, where it came from and what decoded it.'
              : 'Pick an entry to see what it is and everything it links to.'}
          </p>
        ) : (
          <>
            <div>
              <p className={cn('text-sm font-semibold break-words leading-snug', !named && advanced && 'font-mono')}>{head}</p>
              {under && <p className="text-[10px] font-mono text-muted-foreground mt-0.5 break-words">{under}</p>}
            </div>
            {result.ref && links && <Links result={result} groups={links.plain} disc={result.disc ?? result.tags[0] ?? ''} hex={advanced} />}
            {extended && (
              <Extended key={railMode} advanced={advanced}>
                <div className="space-y-3">
                  {infoTitle && <p className="text-[11px] font-mono font-semibold break-words">{infoTitle}</p>}
                  {!!links?.advanced.length && (
                    <div className="space-y-1">
                      <p className="text-[10px] text-muted-foreground">Shown with the links in Advanced mode:</p>
                      <LinkGroups groups={links.advanced} disc={result.disc ?? result.tags[0] ?? ''} dense />
                    </div>
                  )}
                  {info!.lines.length > 0 && <InfoLines lines={info!.lines} />}
                  {pictorial && result.summary && <SummaryView title={result.summary.title} fields={result.summary.fields} className="p-3 shadow-none" />}
                  {pictorial && result.text && (
                    <div>
                      <h3 className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground mb-1">Details</h3>
                      <pre className="text-[10px] leading-relaxed font-mono whitespace-pre-wrap break-words rounded-md bg-muted p-2">
                        {result.text.split('\n').map((line, i) => (
                          <span key={i} className="block">
                            {line || ' '}
                          </span>
                        ))}
                      </pre>
                    </div>
                  )}
                </div>
              </Extended>
            )}
          </>
        )}
      </div>
      <div className="border-t border-border p-3 space-y-1.5">
        <p className="text-[10px] uppercase tracking-wide font-semibold text-muted-foreground">Exports go to</p>
        <button
          className="w-full text-left text-[10px] font-mono text-muted-foreground hover:text-primary break-words cursor-pointer flex gap-1.5"
          title="Show the exports folder"
          onClick={() => void api.reveal(exportsDir).catch(() => {})}
        >
          <FolderOpen className="w-3 h-3 shrink-0 mt-px" />
          {exportsDir}
        </button>
        <p className="text-[10px] text-muted-foreground">{tab.name} · {result?.program ?? session.program}</p>
      </div>
    </aside>
  )
}

/** The provider's info lines: `key: value` rows, free lines and warnings;
 *  a `source:` line — what kind of bytes it was decoded from — as a badge. */
function InfoLines({ lines }: { lines: InfoLine[] }) {
  return (
    <div className="space-y-1.5">
      {lines.map((l, i) =>
        'warn' in l ? (
          <p key={i} className="text-[11px] rounded-md bg-warn-soft text-warn px-2 py-1 flex gap-1.5">
            <TriangleAlert className="w-3 h-3 mt-0.5 shrink-0" /> {l.warn}
          </p>
        ) : 'k' in l ? (
          <div key={i} className="grid grid-cols-[88px_1fr] gap-2 text-[11px]">
            <span className="text-muted-foreground truncate" title={l.k}>
              {l.k}
            </span>
            {l.k === 'source' ? (
              <span>
                <Badge tone={kindTone(l.v)} title={kindTone(l.v) === 'ok' ? 'What the bytes were decoded from' : 'Not a source kind the decoders know'}>
                  {l.v}
                </Badge>
              </span>
            ) : (
              <span className="font-mono break-words min-w-0">{l.v}</span>
            )}
          </div>
        ) : (
          <p key={i} className="text-[11px] font-mono text-secondary-foreground break-words">
            {l.line}
          </p>
        ),
      )}
    </div>
  )
}

/** What the thing links to and what links to it, and its own card. */
function Links({ result, groups, disc, hex }: { result: Result; groups: LinkGroup[]; disc: string; hex: boolean }) {
  const ref = result.ref!
  return (
    <div className="space-y-2">
      <div className="flex items-center">
        <h3 className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground flex-1">Links</h3>
        <button
          className="h-6 px-1.5 rounded text-[11px] text-muted-foreground hover:text-primary hover:bg-accent flex items-center gap-1 cursor-pointer"
          title="Open its card: what it is, and everything it links to"
          onClick={() => nav.open(ref, disc)}
        >
          <IdCard className="w-3.5 h-3.5" /> Open card
        </button>
      </div>
      {groups.length ? (
        <LinkGroups groups={groups} disc={disc} hex={hex} dense />
      ) : (
        <p className="text-[11px] text-muted-foreground">{result.links?.length ? 'Its links are to tabs of Advanced mode: see the extended info.' : 'No links known yet.'}</p>
      )}
    </div>
  )
}
