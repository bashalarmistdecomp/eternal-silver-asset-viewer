import { BadgeCheck, Check, ChevronDown, ChevronRight, Info, TriangleAlert, type LucideIcon } from 'lucide-react'
import { Fragment, useMemo, useState, type ReactNode } from 'react'
import { LinkGroups } from '../../components/RefLink'
import { Badge, type Tone } from '../../components/ui/badge'
import type { LinkGroup, Sheet, SheetPicture, SheetSection } from '../../lib/api'
import { splitAdvanced } from '../../lib/refs'
import { blobUrl } from '../../lib/backend'
import { nav } from '../../lib/nav'
import { tabIcon } from '../../lib/tabs'
import { cn } from '../../lib/utils'

const TONE_ICON: Partial<Record<Tone, LucideIcon>> = { ok: BadgeCheck, warn: TriangleAlert, danger: TriangleAlert }

/** The title of a page's extended info (backend adventure.EXTENDED). */
const EXTENDED = 'Extended info'

/** What Fan mode moves from a section to the page's extended info: what
 *  it cites, and its note where the note cites the code. */
interface Moved {
  title: string
  cite?: string
  note?: string
}

/**
 * The page as Fan mode shows it (docs/taxonomy.md, "The rule": simple to
 * complex): a section's plain note in place of its cited one, no citation
 * by its title, no links to things only Advanced mode has a tab for. What
 * that takes away goes to the extended info: the page's own section of
 * that title, or one put before its other folded sections.
 */
function forFan(sections: SheetSection[]): { sections: SheetSection[]; moved: Moved[]; links: LinkGroup[]; at: number } {
  const moved: Moved[] = []
  const links: LinkGroup[] = []
  const shown: SheetSection[] = sections.map((s) => {
    // an extended section is folded already: it keeps all it says
    if (s.extended) return { ...s, aside: [s.aside, s.cite].filter(Boolean).join(' · ') || undefined, cite: undefined }
    const cited = s.fanNote !== undefined && !!s.note
    if (s.cite || cited) moved.push({ title: s.title, cite: s.cite, note: cited ? s.note : undefined })
    const split = s.links ? splitAdvanced(s.links) : null
    if (split) links.push(...split.advanced)
    return { ...s, cite: undefined, note: s.fanNote !== undefined ? s.fanNote : s.note, links: split?.plain }
  })
  // the page's own "Extended info", or one put before its other folded
  // sections (a file's facts, what proves it)
  let at = shown.findIndex((s) => s.extended && s.title === EXTENDED)
  if (at < 0 && (moved.length || links.length)) {
    const first = shown.findIndex((s) => s.extended)
    at = first < 0 ? shown.length : first
    shown.splice(at, 0, { title: EXTENDED, extended: true })
  }
  return { sections: shown, moved, links, at }
}

/** A page the provider described and the app lays out: a heading with
 *  its picture and badges, then one card per section. A section can be
 *  the result's `sound`, laid out in its place; an extended one is folded
 *  in Fan mode (not `advanced`), and Fan mode moves what a section cites
 *  there (`forFan`). */
export function SheetView({ sheet, disc, advanced, sound }: { sheet: Sheet; disc?: string; advanced?: boolean; sound?: ReactNode }) {
  const fan = useMemo(() => (advanced ? null : forFan(sheet.sections)), [sheet, advanced])
  const sections = fan?.sections ?? sheet.sections
  const picture = sheet.picture
  // blown up by a whole number, to about 96 pixels; pixels kept square
  const scale = picture ? Math.max(1, Math.min(4, Math.floor(96 / Math.max(picture.w, picture.h)))) : 1
  return (
    <div className="w-full max-w-3xl space-y-4 selectable animate-fade-in">
      <header className="rounded-lg border border-border bg-card shadow-sm p-5 flex gap-4 items-start">
        {picture && (
          <img
            src={blobUrl(picture.blob, 'png')}
            width={picture.w * scale}
            height={picture.h * scale}
            alt=""
            draggable={false}
            className="[image-rendering:pixelated] rounded-sm bg-muted/40 shrink-0"
          />
        )}
        <div className="min-w-0 flex-1">
          <h2 className={cn('text-base font-semibold leading-snug break-words', sheet.titleMono && 'font-mono')}>{sheet.title}</h2>
          {sheet.subtitle && <p className="text-xs text-muted-foreground mt-1">{sheet.subtitle}</p>}
          {!!sheet.badges?.length && (
            <div className="flex flex-wrap gap-1.5 mt-3">
              {sheet.badges.map((b, i) => {
                const Icon = TONE_ICON[b.tone]
                return (
                  <Badge key={i} tone={b.tone} title={b.hint} className="h-5 px-2 text-[11px] font-sans">
                    {Icon && <Icon className="w-3 h-3" />}
                    {b.text}
                  </Badge>
                )
              })}
            </div>
          )}
        </div>
      </header>
      {sections.map((s, i) =>
        s.sound ? (
          <Fragment key={i}>{sound}</Fragment>
        ) : (
          <Section
            key={`${i}|${!!advanced}`}
            section={s}
            disc={disc}
            advanced={advanced}
            moved={fan && i === fan.at ? fan.moved : undefined}
            movedLinks={fan && i === fan.at ? fan.links : undefined}
          />
        ),
      )}
    </div>
  )
}

function Section({
  section: s,
  disc,
  advanced,
  moved,
  movedLinks,
}: {
  section: SheetSection
  disc?: string
  advanced?: boolean
  /** Fan mode's extended info: what the other sections cite, and their
   *  links to things only Advanced mode has a tab for. */
  moved?: Moved[]
  movedLinks?: LinkGroup[]
}) {
  const [open, setOpen] = useState(!s.extended || !!advanced)
  const keysAsData = s.style === 'glossary'
  const valuesAsData = !s.style || s.style === 'facts'
  // On first; when every off chip is off for one reason, it is said once.
  const chips = [...(s.chips ?? [])].sort((a, b) => Number(b.on) - Number(a.on))
  const whys = new Set(chips.filter((c) => !c.on).map((c) => c.why ?? ''))
  const sharedWhy = whys.size === 1 ? [...whys][0] : null
  return (
    <section className="rounded-lg border border-border bg-card shadow-sm overflow-hidden">
      <div className={cn('px-4 h-9 flex items-center gap-3', open && 'border-b border-border/70')}>
        {s.extended ? (
          <button
            className="flex-1 flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground hover:text-foreground cursor-pointer text-left"
            onClick={() => setOpen((o) => !o)}
          >
            {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
            {s.title}
          </button>
        ) : (
          <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground flex-1">{s.title}</h3>
        )}
        {/* a folded section says what it cites once it is opened */}
        {(s.aside || s.cite) && open && (
          <span className="text-[10px] font-mono text-muted-foreground truncate">{[s.aside, s.cite].filter(Boolean).join(' · ')}</span>
        )}
      </div>
      <div className={cn('p-4 space-y-3', !open && 'hidden')}>
        {!!s.fields?.length && (
          <dl className="grid grid-cols-[minmax(110px,max-content)_1fr] gap-x-5 gap-y-2 text-xs">
            {s.fields.map(([k, v, hint], i) => (
              <div key={i} className="contents">
                <dt className={cn(keysAsData ? 'font-mono text-foreground' : 'text-muted-foreground')}>{k}</dt>
                <dd className="min-w-0 flex flex-wrap items-baseline gap-x-2">
                  <span className={cn('min-w-0 break-words', valuesAsData ? 'font-mono' : 'text-secondary-foreground leading-relaxed')}>{v}</span>
                  {hint && <span className="text-[11px] text-muted-foreground">{hint}</span>}
                </dd>
              </div>
            ))}
          </dl>
        )}
        {!!chips.length && (
          <div className="grid gap-1.5" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))' }}>
            {chips.map((c) => {
              const Icon = tabIcon(c.icon ?? '')
              return (
                <div
                  key={c.label}
                  title={c.on ? `${c.label}: on` : `${c.label}: off, ${c.why}`}
                  className={cn(
                    'rounded-md border px-2 py-1.5 flex items-start gap-2 min-w-0',
                    c.on ? 'border-primary/20 bg-accent/50' : 'border-dashed border-border text-muted-foreground',
                  )}
                >
                  <Icon className={cn('w-3.5 h-3.5 shrink-0 mt-px', c.on ? 'text-primary' : 'opacity-60')} />
                  <span className="min-w-0 flex-1">
                    <span className={cn('block text-xs truncate', c.on && 'font-medium')}>{c.label}</span>
                    {!c.on && c.why && sharedWhy === null && <span className="block text-[10px] leading-tight truncate">{c.why}</span>}
                  </span>
                  {c.on && <Check className="w-3 h-3 text-ok shrink-0 mt-0.5" />}
                </div>
              )
            })}
          </div>
        )}
        {!!sharedWhy && (
          <p className="text-[11px] text-muted-foreground">
            Off here: {sharedWhy.startsWith('serves ') ? `these tabs serve ${sharedWhy.slice(7)}` : sharedWhy}
          </p>
        )}
        {s.verdict && <Verdict text={s.verdict.text} tone={s.verdict.tone} />}
        {s.hex && <HexView offset={s.hex.offset} bytes={s.hex.bytes} />}
        {s.table && <SheetTable {...s.table} />}
        {!!s.list?.length && (
          <ul className="space-y-1 text-xs font-mono">
            {s.list.map((item, i) => (
              <li key={i} className="flex gap-2 items-baseline">
                <span className="w-1 h-1 rounded-full bg-muted-foreground/60 shrink-0 translate-y-[-2px]" />
                <span className="min-w-0 break-words">{item}</span>
              </li>
            ))}
          </ul>
        )}
        {!!s.pictures?.length && <Pictures pictures={s.pictures} disc={disc} />}
        {!!s.links?.length && disc && <LinkGroups groups={s.links} disc={disc} hex={advanced} />}
        {s.note &&
          s.note.split(/\n\s*\n/).map((p, i) => (
            <p key={i} className="text-xs leading-relaxed text-secondary-foreground">
              {p}
            </p>
          ))}
        {!!moved?.length && (
          <dl className="grid grid-cols-[minmax(110px,max-content)_1fr] gap-x-5 gap-y-2 text-xs">
            {moved.map((m, i) => (
              <div key={i} className="contents">
                <dt className="text-muted-foreground">{m.title}</dt>
                <dd className="min-w-0 space-y-1.5">
                  {m.cite && <span className="block font-mono break-words">{m.cite}</span>}
                  {m.note?.split(/\n\s*\n/).map((p, j) => (
                    <p key={j} className="leading-relaxed text-secondary-foreground">
                      {p}
                    </p>
                  ))}
                </dd>
              </div>
            ))}
          </dl>
        )}
        {!!movedLinks?.length && disc && <LinkGroups groups={movedLinks} disc={disc} />}
      </div>
    </section>
  )
}

/** Pictures at twice their size, pixels kept square; one with a ref opens its card. */
function Pictures({ pictures, disc }: { pictures: SheetPicture[]; disc?: string }) {
  return (
    <div className="flex flex-wrap gap-3">
      {pictures.map((p, i) => {
        const body = (
          <>
            <img
              src={blobUrl(p.blob, 'png')}
              width={p.w * 2}
              height={p.h * 2}
              alt={p.caption ?? ''}
              draggable={false}
              className="[image-rendering:pixelated] rounded-sm bg-muted/40"
            />
            {p.caption && <span className="block mt-1 text-[11px] text-muted-foreground text-center">{p.caption}</span>}
          </>
        )
        const ref = p.ref
        return ref && disc ? (
          <button
            key={i}
            type="button"
            title="Open its card"
            onClick={() => nav.open(ref, disc)}
            className="rounded-md p-1 -m-1 hover:bg-accent/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {body}
          </button>
        ) : (
          <figure key={i} className="m-0">
            {body}
          </figure>
        )
      })}
    </div>
  )
}

const VERDICT: Partial<Record<Tone, string>> = {
  ok: 'bg-ok-soft text-ok',
  warn: 'bg-warn-soft text-warn',
  danger: 'bg-destructive/10 text-destructive',
  info: 'bg-info-soft text-info',
}

function Verdict({ text, tone }: { text: string; tone: Tone }) {
  const Icon = TONE_ICON[tone] ?? Info
  return (
    <p className={cn('rounded-md px-2.5 py-1.5 text-[11px] flex gap-1.5', VERDICT[tone] ?? 'bg-muted text-muted-foreground')}>
      <Icon className="w-3.5 h-3.5 shrink-0" />
      <span>{text}</span>
    </p>
  )
}

/** A small table inside a card: numbers right-aligned in the mono face, words left. */
function SheetTable({ columns, rows, align }: { columns: string[]; rows: string[][]; align?: ('left' | 'right')[] }) {
  const right = (c: number) => align?.[c] === 'right'
  return (
    <div className="-mx-4 -my-1 overflow-x-auto">
      <table className="w-full text-[11px] border-separate border-spacing-0">
        <thead>
          <tr>
            {columns.map((c, i) => (
              <th
                key={i}
                className={cn(
                  'px-2 first:pl-4 last:pr-4 pb-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground border-b border-border/70 whitespace-nowrap',
                  right(i) ? 'text-right' : 'text-left',
                )}
              >
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="hover:bg-muted/60">
              {r.map((v, c) => (
                <td
                  key={c}
                  className={cn(
                    'px-2 first:pl-4 last:pr-4 py-1 border-b border-border/40 align-top',
                    right(c) ? 'text-right font-mono tabular-nums whitespace-nowrap' : 'text-secondary-foreground',
                  )}
                >
                  {v}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

const hex = (n: number, digits: number) => n.toString(16).toUpperCase().padStart(digits, '0')
const printable = (b: number) => b >= 0x20 && b < 0x7f
/** Characters a row of `n` bytes takes: two each, a space between, two before the ninth. */
const rowWidth = (n: number) => (n ? n * 3 - 1 + (n > 8 ? 1 : 0) : 0)

/**
 * Bytes as a hex editor shows them: offset, sixteen bytes in two groups of
 * eight, and their ASCII. A zero is dimmed and a printable byte tinted, so
 * text and padding stand out; pointing at a byte lights it on both sides
 * and says where it is.
 */
function HexView({ offset, bytes }: { offset: number; bytes: string }) {
  const data = useMemo(() => (bytes.match(/../g) ?? []).map((h) => parseInt(h, 16)), [bytes])
  const [at, setAt] = useState<number | null>(null)
  const digits = Math.max(4, hex(offset + data.length, 1).length)
  const rows = Array.from({ length: Math.ceil(data.length / 16) }, (_, r) => data.slice(r * 16, r * 16 + 16))
  const tint = (b: number) => (b === 0 ? 'text-muted-foreground/45' : printable(b) ? 'text-info' : 'text-foreground')
  const lit = 'bg-primary/15 text-primary rounded-sm'
  return (
    <div className="space-y-2">
      <div className="font-mono text-[11px] leading-5 overflow-x-auto whitespace-pre" onMouseLeave={() => setAt(null)}>
        {rows.map((row, r) => (
          <div key={r} className="flex gap-5">
            <span className="text-muted-foreground/70">{hex(offset + r * 16, digits)}</span>
            <span>
              {row.map((b, i) => {
                const k = r * 16 + i
                return (
                  <span key={i}>
                    {i > 0 && (i === 8 ? '  ' : ' ')}
                    <span className={cn(tint(b), at === k && lit)} onMouseEnter={() => setAt(k)}>
                      {hex(b, 2)}
                    </span>
                  </span>
                )
              })}
              {' '.repeat(rowWidth(16) - rowWidth(row.length))}
            </span>
            <span className="border-l border-border pl-3">
              {row.map((b, i) => {
                const k = r * 16 + i
                return (
                  <span key={i} className={cn(printable(b) ? 'text-secondary-foreground' : 'text-muted-foreground/45', at === k && lit)} onMouseEnter={() => setAt(k)}>
                    {printable(b) ? String.fromCharCode(b) : '.'}
                  </span>
                )
              })}
            </span>
          </div>
        ))}
      </div>
      <p className="text-[11px] text-muted-foreground font-mono h-4">
        {at === null
          ? 'Point at a byte to see where it is.'
          : `offset 0x${hex(offset + at, digits)} (${offset + at}) · byte 0x${hex(data[at], 2)} = ${data[at]}${printable(data[at]) ? ` · '${String.fromCharCode(data[at])}'` : ''}`}
      </p>
    </div>
  )
}
