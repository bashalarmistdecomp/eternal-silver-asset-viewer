import { ArrowLeft, ArrowRight, ChevronDown, ChevronRight, LoaderCircle, Play, SquareArrowOutUpRight, TriangleAlert, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Badge } from '../components/ui/badge'
import { KindIcon, LinkGroups } from '../components/RefLink'
import { api, type Card, type Session } from '../lib/api'
import { blobUrl } from '../lib/backend'
import { isAsking } from '../lib/confirm'
import { nav, useNav, type CardEntry } from '../lib/nav'
import { refKey, splitAdvanced } from '../lib/refs'
import { playable, type PlaySong } from '../lib/songs'
import { inRail, type RailMode } from '../lib/tabs'
import { cn, keyName } from '../lib/utils'

const entryKey = (e: CardEntry) => `${e.disc}|${refKey(e.ref)}`

/** The biggest a card's picture is drawn, in screen pixels. */
const PICTURE = 176
/** A picture at least this many times as wide as tall (a message's window) spans the card. */
const WIDE = 2
/** The card's inner width, for a wide picture. */
const CARD_INNER = 600

/**
 * The card of the thing a link points at, over the disc view: what it is in
 * plain words, its picture, its links, and the extended info (folded in Fan
 * mode, open in Advanced). It shows while the history's current entry is a
 * card (lib/nav.ts); Back and Forward walk the history, and closing it
 * returns to the place the cards were opened from.
 */
export function CardHost({
  session,
  railMode,
  onRailMode,
  playSong,
}: {
  session: Session
  railMode: RailMode
  onRailMode: (m: RailMode) => void
  playSong: PlaySong
}) {
  const { current, canBack, canForward } = useNav()
  const entry = current?.type === 'card' ? current : null
  const cache = useRef(new Map<string, Card>())
  const [card, setCard] = useState<Card | null>(null)
  const [error, setError] = useState<string | null>(null)
  const key = entry ? entryKey(entry) : null

  useEffect(() => {
    if (!entry || !key) return
    const have = cache.current.get(key)
    setError(null)
    if (have) return setCard(have)
    setCard(null)
    let live = true
    api
      .card(session.id, entry.ref, entry.disc)
      .then((c) => {
        cache.current.set(key, c)
        if (live) setCard(c)
      })
      .catch((e) => live && setError(e instanceof Error ? e.message : String(e)))
    return () => {
      live = false
    }
    // the entry is read through its key
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, session.id])

  useEffect(() => {
    if (!entry) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !isAsking()) {
        e.preventDefault()
        nav.close()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [entry])

  if (!entry) return null
  const advanced = railMode === 'advanced'
  const shown = card && entryKey({ type: 'card', ref: card.ref, disc: card.disc }) === key ? card : null

  return createPortal(
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/30" onMouseDown={() => nav.close()}>
      <div
        className="relative bg-card border border-border rounded-lg shadow-xl max-h-[85vh] w-[640px] max-w-[calc(100vw-32px)] flex flex-col"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="px-3 py-2.5 border-b border-border flex items-center gap-2">
          <HeadButton title={`Back (${keyName('Alt', '←')})`} disabled={!canBack} onClick={() => nav.back()}>
            <ArrowLeft className="w-4 h-4" />
          </HeadButton>
          <HeadButton title={`Forward (${keyName('Alt', '→')})`} disabled={!canForward} onClick={() => nav.forward()}>
            <ArrowRight className="w-4 h-4" />
          </HeadButton>
          <Badge tone="primary" className="font-sans">
            <KindIcon kind={entry.ref.kind} className="w-3 h-3" />
            {shown?.kindName ?? entry.ref.kind}
          </Badge>
          <h2 className="text-sm font-semibold truncate flex-1 min-w-0 selectable">{shown?.title ?? ''}</h2>
          {shown && (
            <span className="text-[11px] font-mono text-muted-foreground shrink-0 selectable">
              {shown.written}
              {advanced && shown.hex !== shown.written && ` · ${shown.hex}`}
            </span>
          )}
          <HeadButton title="Close (Esc)" onClick={() => nav.close()}>
            <X className="w-4 h-4" />
          </HeadButton>
        </div>
        <div className="flex-1 min-h-0 overflow-y-auto p-4 space-y-4 selectable">
          {error ? (
            <Banner text={error} />
          ) : !shown ? (
            <p className="text-xs text-muted-foreground flex items-center gap-2">
              <LoaderCircle className="w-3.5 h-3.5 animate-spin" /> Reading…
            </p>
          ) : (
            <CardBody key={`${key}|${railMode}`} card={shown} advanced={advanced} />
          )}
        </div>
        {shown && (
          <Footer card={shown} railMode={railMode} onRailMode={onRailMode} playSong={playSong} />
        )}
      </div>
    </div>,
    document.body,
  )
}

function HeadButton({ title, disabled, onClick, children }: { title: string; disabled?: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      title={title}
      disabled={disabled}
      onClick={onClick}
      className="h-7 w-7 shrink-0 rounded flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-accent cursor-pointer disabled:opacity-35 disabled:cursor-default disabled:hover:bg-transparent"
    >
      {children}
    </button>
  )
}

function Banner({ text }: { text: string }) {
  return (
    <p className="text-[11px] rounded-md bg-warn-soft text-warn px-2 py-1.5 flex gap-1.5 break-words">
      <TriangleAlert className="w-3 h-3 mt-0.5 shrink-0" /> {text}
    </p>
  )
}

function CardBody({ card, advanced }: { card: Card; advanced: boolean }) {
  const [open, setOpen] = useState(advanced)
  // Fan mode shows the links to things only Advanced mode has a tab for
  // (a resource, a sound bank) with the extended info
  const links = advanced ? { plain: card.groups, advanced: [] } : splitAdvanced(card.groups)
  const pic = card.picture
  const wide = !!pic && pic.w >= WIDE * pic.h
  const scale = pic ? (wide ? (CARD_INNER - 16) / pic.w : Math.min(PICTURE / pic.w, PICTURE / pic.h)) : 1
  const fit = scale >= 1 ? Math.floor(scale) : scale
  const picture = pic && (
    <div className={cn('rounded-md bg-stage p-2 flex items-center justify-center', !wide && 'shrink-0')} style={{ minWidth: 64, minHeight: 64 }}>
      <img
        src={blobUrl(pic.blob, 'png')}
        alt=""
        width={Math.round(pic.w * fit)}
        height={Math.round(pic.h * fit)}
        className="[image-rendering:pixelated]"
        draggable={false}
      />
    </div>
  )
  return (
    <>
      {card.error && <Banner text={card.error} />}
      {wide && picture}
      <div className="flex gap-4">
        {!wide && picture}
        <div className="min-w-0 flex-1 space-y-2">
          {card.subtitle && <p className="text-xs text-secondary-foreground">{card.subtitle}</p>}
          {card.facts.length > 0 && (
            <div className="space-y-1">
              {card.facts.map(([k, v], i) => (
                <div key={i} className="grid grid-cols-[120px_1fr] gap-2 text-[11px]">
                  <span className="text-muted-foreground">{k}</span>
                  <span className="break-words min-w-0">{v}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
      {card.note &&
        card.note.split(/\n\s*\n/).map((p, i) => (
          <p key={i} className="text-xs leading-relaxed text-secondary-foreground whitespace-pre-line">
            {p}
          </p>
        ))}
      {links.plain.length > 0 && <LinkGroups groups={links.plain} disc={card.disc} hex={advanced} />}
      <div className="border-t border-border pt-3">
        <button
          className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground hover:text-foreground cursor-pointer"
          onClick={() => setOpen((o) => !o)}
        >
          {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
          Extended info
        </button>
        {open && (
          <div className="mt-2 space-y-1">
            {card.extended.map(([k, v], i) => (
              <div key={i} className="grid grid-cols-[120px_1fr] gap-2 text-[11px]">
                <span className="text-muted-foreground">{k}</span>
                <span className="font-mono break-words min-w-0">{v}</span>
              </div>
            ))}
            {card.proven.length > 0 && (
              <div className="grid grid-cols-[120px_1fr] gap-2 text-[11px]">
                <span className="text-muted-foreground">Proven by</span>
                <span className="font-mono break-words min-w-0">{card.proven.join(', ')}</span>
              </div>
            )}
            {links.advanced.length > 0 && (
              <div className="pt-2">
                <LinkGroups groups={links.advanced} disc={card.disc} />
              </div>
            )}
          </div>
        )}
      </div>
    </>
  )
}

function Footer({
  card,
  railMode,
  onRailMode,
  playSong,
}: {
  card: Card
  railMode: RailMode
  onRailMode: (m: RailMode) => void
  playSong: PlaySong
}) {
  const [busy, setBusy] = useState(false)
  const homes = card.homes ?? (card.home ? [card.home] : [])
  return (
    <div className="px-4 py-2.5 border-t border-border flex items-center gap-2">
      {playable(card.kind) && (
        <button
          className="h-7 px-2.5 rounded-md bg-primary text-primary-foreground text-xs flex items-center gap-1.5 cursor-pointer hover:bg-primary/90 disabled:opacity-60"
          disabled={busy}
          onClick={() => {
            setBusy(true)
            void playSong(card.ref, card.title, card.disc).finally(() => setBusy(false))
          }}
        >
          {busy ? <LoaderCircle className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />} Play
        </button>
      )}
      <div className="flex-1" />
      {homes.length ? (
        homes.map((home) => {
          // a home only Advanced mode's rail shows switches to it
          const switches = railMode === 'fan' && !inRail(home.key, 'fan')
          const where = home.view ? `${home.name} · ${home.view}` : home.name
          return (
            <button
              key={home.tab}
              className={cn('h-7 px-2.5 rounded-md border border-border text-xs flex items-center gap-1.5 cursor-pointer hover:border-primary/50 hover:text-primary')}
              title={switches ? `${home.name} is a tab of Advanced mode: this switches to it` : `Show it in ${where}`}
              onClick={() => {
                if (switches) onRailMode('advanced')
                nav.go({ tab: home.tab, view: home.view, item: home.item, version: home.version })
              }}
            >
              <SquareArrowOutUpRight className="w-3.5 h-3.5" />
              Open in {home.name}
              {switches && <span className="text-muted-foreground">(Advanced)</span>}
            </button>
          )
        })
      ) : (
        <span className="text-[11px] text-muted-foreground">No tab shows it on its own yet</span>
      )}
    </div>
  )
}
