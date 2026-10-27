import { BadgeCheck, Disc3, TriangleAlert, X } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Badge } from '../components/ui/badge'
import { Dialog } from '../components/ui/dialog'
import { Segmented } from '../components/ui/segmented'
import { toast } from '../components/ui/toast'
import { api, type MusicOverview, type Ref, type Result, type Row, type Session } from '../lib/api'
import { isAsking } from '../lib/confirm'
import { isCardOpen, nav, useNav, type NavEntry, type PlaceEntry } from '../lib/nav'
import { PlaySongContext } from '../lib/songs'
import { transport, useTransport, type Loaded } from '../lib/transport'
import { firstView, PARTIAL, type RailMode } from '../lib/tabs'
import { useStored } from '../lib/hooks'
import { forControl, inField } from '../lib/utils'
import { CardHost } from './CardHost'
import { Inspector } from './Inspector'
import { ItemList, type ItemListHandle } from './ItemList'
import { AboutText, Stage } from './Stage'

interface TabState {
  view: string | null
  rows: Record<string, Row[]>
  selected: number | null
  result: Result | null
  /** The view and row `result` is of ("view|row"). */
  shown?: string | null
  /** Re-select this row once the (new) view's items are in. */
  pending?: number | null
  /** The selection being decoded for this tab (its number), and the error
   *  the last one ended in: each tab shows its own. */
  selecting?: number | null
  selectError?: string | null
}

const shownKey = (view: string | null, row: number) => `${view ?? ''}|${row}`

const viewKey = (v: string | null) => v ?? ''

/** A tab's view's list: "tab|view". */
const listKey = (tab: number, view: string | null) => `${tab}|${viewKey(view)}`

/** Number a new selection in tab `tab`: the replies to its older ones are dropped. */
const nextIn = (seq: Record<number, number>, tab: number) => (seq[tab] = (seq[tab] ?? 0) + 1)

/** What the transport would hold for a selection: its clip, if it has one. */
export function clipOf(session: Session, tabName: string, r: Result | null, title?: string): Loaded | null {
  if (!r?.audio?.wav && !r?.audio?.live) return null
  const name = title ?? r.label.trim()
  return { clip: r.audio, resultId: r.id, sessionId: session.id, source: `${tabName} · ${name}`, title: name, program: r.program }
}

/** A result with the overview's news: more waveform columns, and once the
 *  whole score has been played, the text and info that needed it. */
function withOverview(r: Result, o: MusicOverview): Result {
  const w = r.waveform
  const out: Result = { ...r }
  if (w) {
    const have = w.lo.length
    const lo = o.from === have ? w.lo.concat(o.lo) : w.lo
    const hi = o.from === have ? w.hi.concat(o.hi) : w.hi
    out.waveform = { ...w, lo, hi, pending: !o.done, note: o.error ? `waveform: ${o.error}` : w.note }
  }
  if (o.text !== undefined) out.text = o.text
  if (o.info !== undefined) out.info = o.info
  return out
}

/** The version of a row to show: the one on the disc last chosen, if any. */
function versionFor(row: Row | undefined, prefer: string | null): number {
  if (!row?.versions || !prefer) return 0
  const at = row.versions.findIndex((tags) => tags.includes(prefer))
  return at < 0 ? 0 : at
}

/**
 * One open game: the tab's item list, the stage, the inspector. Each tab
 * keeps its own view, list and selection, so switching away and back
 * returns to where you were. Items come from every disc of the game, each
 * tagged with the discs that hold it; a row whose discs hold different
 * contents has a version switch above the stage.
 */
export function DiscView({
  session,
  tab,
  railMode,
  onTab,
  onRailMode,
  onClose,
}: {
  session: Session
  tab: number
  railMode: RailMode
  /** Show another tab (following a link to it). */
  onTab: (index: number) => void
  onRailMode: (m: RailMode) => void
  onClose: () => void
}) {
  const meta = session.tabs[tab] ?? session.tabs[0]
  const [tabs, setTabs] = useState<Record<number, TabState>>({})
  // The lists whose fetch failed, by tab and view (listKey); a list neither
  // in nor failed is being fetched.
  const [listErrors, setListErrors] = useState<Record<string, string>>({})
  const [about, setAbout] = useState(false)
  // The disc whose version to show where a row has several: the last chosen.
  const [prefer, setPrefer] = useState<string | null>(null)
  const listRef = useRef<ItemListHandle>(null)
  // The latest selection asked of each tab. Per tab: one still being
  // decoded in a tab left meanwhile lands there all the same.
  const seq = useRef<Record<number, number>>({})
  // The tab in front, for the replies that land after the person left theirs.
  const front = useRef(meta.index)
  useEffect(() => {
    front.current = meta.index
  }, [meta.index])
  const keyTimer = useRef(0)
  const t = useTransport()
  // The result whose overview is being followed, per tab.
  const following = useRef<Record<number, string>>({})
  // The game closed (or left for the library) follows nothing more: each
  // poll stops at its next turn, its reply dropped.
  useEffect(() => {
    const now = following
    return () => {
      now.current = {}
    }
  }, [])

  // A tab's first view: in Advanced mode its technical one. A tab already
  // shown keeps its own when the mode changes.
  const fresh = useCallback(
    (index: number): TabState => {
      const m = session.tabs[index]
      return { view: m ? firstView(m, railMode) : null, rows: {}, selected: null, result: null }
    },
    [session.tabs, railMode],
  )
  const state: TabState = tabs[meta.index] ?? fresh(meta.index)
  const rows = state.rows[viewKey(state.view)] ?? null
  const itemsError = listErrors[listKey(meta.index, state.view)] ?? null
  const loadingItems = rows === null && itemsError === null

  const patch = useCallback(
    (index: number, p: Partial<TabState>) => {
      setTabs((all) => {
        const old = all[index] ?? fresh(index)
        return { ...all, [index]: { ...old, ...p } }
      })
    },
    [fresh],
  )

  /** A selection in tab `index` ended (answered, failed or dropped): the
   *  tab stops showing it, unless a newer one is under way there. */
  const settle = useCallback((index: number, my: number) => {
    setTabs((all) => {
      const cur = all[index]
      return cur?.selecting === my ? { ...all, [index]: { ...cur, selecting: null } } : all
    })
  }, [])

  /** File a view's rows without disturbing the other views' (an updater, so no stale copy). */
  const putRows = useCallback(
    (index: number, view: string | null, list: Row[]) => {
      setTabs((all) => {
        const old = all[index] ?? fresh(index)
        return { ...all, [index]: { ...old, view: old.view ?? view, rows: { ...old.rows, [viewKey(view)]: list } } }
      })
    },
    [fresh],
  )

  /** Fill a live score's waveform (and what needed the whole score) in as
   *  the server's overview plays it, while the result is still shown. */
  const follow = useCallback(
    async (tabIndex: number, r: Result) => {
      following.current[tabIndex] = r.id
      let have = r.waveform?.lo.length ?? 0
      for (;;) {
        await new Promise((ok) => setTimeout(ok, 250))
        if (following.current[tabIndex] !== r.id) return
        let o: MusicOverview
        try {
          o = await api.musicOverview(session.id, r.id, have, 2)
        } catch {
          // closed by a newer selection: selecting it again draws it
          if (following.current[tabIndex] === r.id) delete following.current[tabIndex]
          return
        }
        if (following.current[tabIndex] !== r.id) return
        setTabs((all) => {
          const cur = all[tabIndex]
          if (!cur?.result || cur.result.id !== r.id) return all
          return { ...all, [tabIndex]: { ...cur, result: withOverview(cur.result, o) } }
        })
        have = o.from + o.lo.length
        if (o.done) return
      }
    },
    [session.id],
  )

  /** Show row `index`. A row with a track takes the transport (asking
   *  first while another is playing: no, and the list goes back to the row
   *  shown); `play` starts it; `quiet` shows it and leaves the transport
   *  be. The row already shown is not fetched again. */
  const select = useCallback(
    async (index: number, opts?: { play?: boolean; version?: number; quiet?: boolean }) => {
      const my = nextIn(seq.current, meta.index)
      window.clearTimeout(keyTimer.current)
      patch(meta.index, { selected: index })
      if (opts?.version === undefined && !opts?.quiet && state.result && state.shown === shownKey(state.view, index)) {
        const clip = clipOf(session, meta.name, state.result, rows?.[index]?.title)
        if (opts?.play && clip && (await transport.take(clip))) void transport.play()
        return
      }
      patch(meta.index, { selecting: my, selectError: null })
      try {
        const version = opts?.version ?? versionFor(rows?.[index], prefer)
        const r = await api.select(session.id, meta.index, state.view, index, version, transport.keep())
        if (my !== seq.current[meta.index]) return
        // A reply for a tab left meanwhile is shown there quietly: the
        // transport is not taken from behind the person's back.
        const quiet = opts?.quiet || front.current !== meta.index
        const clip = clipOf(session, meta.name, r, rows?.[index]?.title)
        if (clip && !quiet && !(await transport.take(clip))) {
          // what plays stays: the list goes back to the row shown
          if (my === seq.current[meta.index]) {
            setTabs((all) => {
              const cur = all[meta.index]
              if (!cur) return all
              const back = cur.shown?.split('|')
              const row = back && back[0] === (cur.view ?? '') ? Number(back[1]) : null
              return { ...all, [meta.index]: { ...cur, selected: row } }
            })
          }
          return
        }
        if (my !== seq.current[meta.index]) return
        patch(meta.index, { result: r, shown: shownKey(state.view, index) })
        if (r.waveform?.pending) void follow(meta.index, r)
        else delete following.current[meta.index]
        if (opts?.play && clip && !quiet) void transport.play()
      } catch (e) {
        if (my !== seq.current[meta.index]) return
        patch(meta.index, { result: null, shown: null, selectError: e instanceof Error ? e.message : String(e) })
      } finally {
        settle(meta.index, my)
      }
    },
    [session, meta, state.view, state.result, state.shown, rows, prefer, patch, settle, follow],
  )

  // The tabs' states as last drawn, for the callbacks that follow links
  // (so they need not change with every selection).
  const tabsNow = useRef(tabs)
  useEffect(() => {
    tabsNow.current = tabs
  }, [tabs])

  /** Show a row of any tab (a link's "Open in", Back and Forward), quietly:
   *  the transport plays on. */
  const showPlace = useCallback(
    async (p: Omit<PlaceEntry, 'type'>) => {
      if (!session.tabs[p.tab]) return
      const my = nextIn(seq.current, p.tab)
      window.clearTimeout(keyTimer.current)
      onTab(p.tab)
      const at = shownKey(p.view, p.item)
      const cur = tabsNow.current[p.tab]
      patch(p.tab, { view: p.view, selected: p.item, pending: null })
      if (cur?.shown === at && cur.result?.version === p.version) return
      patch(p.tab, { selecting: my, selectError: null })
      try {
        const r = await api.select(session.id, p.tab, p.view, p.item, p.version, transport.keep())
        if (my !== seq.current[p.tab]) return
        patch(p.tab, { result: r, shown: at })
        if (r.waveform?.pending) void follow(p.tab, r)
      } catch (e) {
        if (my !== seq.current[p.tab]) return
        patch(p.tab, { result: null, shown: null, selectError: e instanceof Error ? e.message : String(e) })
      } finally {
        settle(p.tab, my)
      }
    },
    [session, onTab, patch, settle, follow],
  )

  // The row shown is where the person is: the history's current place.
  useEffect(() => {
    const r = state.result
    if (!r || state.selected === null || state.shown !== shownKey(state.view, state.selected)) return
    nav.here({ tab: meta.index, view: state.view, item: state.selected, version: r.version })
  }, [meta.index, state.view, state.selected, state.shown, state.result])

  // Back, Forward and "Open in" land on a place: show it.
  const { current } = useNav()
  const lastNav = useRef<NavEntry | null>(null)
  useEffect(() => {
    if (current === lastNav.current) return
    lastNav.current = current
    if (current?.type !== 'place') return
    const st = tabsNow.current[current.tab]
    if (current.tab === meta.index && st?.shown === shownKey(current.view, current.item) && st.result?.version === current.version) return
    void showPlace(current)
  }, [current, meta.index, showPlace])

  /** A music button, or the card of a song or a voice: play it from the
   *  row that is its home (Music, Voices), selecting that row in its tab,
   *  and asking first while another track plays. The one already loaded
   *  pauses or resumes instead. */
  const playSong = useCallback(
    async (song: Ref, title: string, disc?: string) => {
      const bgm = song.id[0]
      const l = transport.state.loaded
      if (song.kind === 'song' && l && l.sessionId === session.id && l.clip.songs?.includes(bgm)) return transport.toggle()
      try {
        const home = await api.locate(session.id, song, disc)
        const at = shownKey(home.view, home.item)
        const there = tabsNow.current[home.tab]
        if (l && there?.shown === at && there.result?.id === l.resultId && there.result.version === home.version) return transport.toggle()
        if (!(await transport.ask(title))) return
        // a selection still on its way in that tab is overtaken by this one
        nextIn(seq.current, home.tab)
        const r = await api.select(session.id, home.tab, home.view, home.item, home.version, transport.keep())
        const clip = clipOf(session, session.tabs[home.tab]?.name ?? '', r, title)
        patch(home.tab, { view: home.view, selected: home.item, result: r, shown: at, pending: null })
        if (r.waveform?.pending) void follow(home.tab, r)
        if (clip) {
          transport.load(clip)
          void transport.play()
        }
      } catch (e) {
        toast({ tone: 'error', title: `Could not play ${title}`, body: e instanceof Error ? e.message : String(e) })
      }
    },
    [session, patch, follow],
  )

  // The tab's items, fetched once per view. A list left before it is in,
  // or failed, is asked for again on the next visit.
  const listed = rows !== null
  useEffect(() => {
    if (listed) return
    let live = true
    const key = listKey(meta.index, state.view)
    api
      .items(session.id, meta.index, state.view)
      .then((items) => live && putRows(meta.index, items.view, items.rows))
      .catch((e) => live && setListErrors((all) => ({ ...all, [key]: e instanceof Error ? e.message : String(e) })))
    return () => {
      live = false
      setListErrors((all) => {
        if (!(key in all)) return all
        const rest = { ...all }
        delete rest[key]
        return rest
      })
    }
  }, [session.id, meta.index, state.view, listed, putRows])

  // A tab whose only row is a placeholder explains itself on arrival; the
  // Disc tab opens on its identity page.
  useEffect(() => {
    if (!rows || state.selected !== null || state.selecting || (state.pending ?? null) !== null) return
    if ((rows.length === 1 && rows[0].empty) || meta.key === 'disc') void select(0)
  }, [rows, state.selected, state.pending, state.selecting, meta.key, select])

  // Arriving on a tab: a score whose waveform was still being drawn when
  // another selection closed its stream is selected again, to finish it
  // (quietly: the transport plays on). The transport's own stream is
  // never closed, so its waveform just goes on.
  const arrived = useRef<number | null>(null)
  useEffect(() => {
    if (arrived.current === meta.index) return
    arrived.current = meta.index
    const r = state.result
    if (r?.waveform?.pending && state.selected !== null && following.current[meta.index] !== r.id) {
      if (transport.state.loaded?.resultId === r.id) void follow(meta.index, r)
      else void select(state.selected, { quiet: true })
    }
  }, [meta.index, state.result, state.selected, select, follow])

  // Another view of the same tab shows the row you were on, another way —
  // or, where views list different items (Sound), the same ROW, when the
  // new list is long enough to have it.
  const changeView = (v: string) => {
    if (v === state.view) return
    nextIn(seq.current, meta.index)
    patch(meta.index, { view: v, selected: null, result: null, pending: state.selected, selecting: null, selectError: null })
  }
  useEffect(() => {
    if (!rows || state.pending === null || state.pending === undefined) return
    const at = state.pending
    patch(meta.index, { pending: null })
    if (at < rows.length) void select(at)
  }, [rows, state.pending, meta.index, patch, select])

  const [inspectorOpen, setInspectorOpen] = useStored('inspector.open', true)
  const toggleInspector = useCallback(() => setInspectorOpen((o) => !o), [setInspectorOpen])

  // Keys that belong to the disc view. Space and ? are the app's; Enter on
  // a focused button presses it.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isAsking() || isCardOpen()) return
      if (inField(e) || e.ctrlKey || e.metaKey || e.altKey) {
        if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
          e.preventDefault()
          if (state.result?.text !== undefined && !state.result.layers) window.dispatchEvent(new Event('viewer:find'))
          else listRef.current?.focusSearch()
        }
        return
      }
      if (forControl(e)) return
      const zoom = (d: string) => window.dispatchEvent(new CustomEvent('viewer:zoom', { detail: d }))
      if (e.key === 'ArrowDown' || e.key === 'j' || e.key === 'ArrowUp' || e.key === 'k') {
        e.preventDefault()
        const delta = e.key === 'ArrowDown' || e.key === 'j' ? 1 : -1
        listRef.current?.step(delta)
      } else if (e.key === 'Enter' && state.selected !== null) {
        e.preventDefault()
        void select(state.selected, { play: true })
      } else if (e.key === '/') {
        e.preventDefault()
        listRef.current?.focusSearch()
      } else if (e.key === '+' || e.key === '=') zoom('in')
      else if (e.key === '-' || e.key === '_') zoom('out')
      else if (e.key === '0') zoom('fit')
      else if (e.key === '1') zoom('1')
      else if (e.key === 'g') zoom('grid')
      else if (e.key === 'i') toggleInspector()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [state.selected, state.result, select, toggleInspector])

  const onSeek = useCallback(
    (seconds: number) => {
      const clip = clipOf(session, meta.name, state.result, state.selected !== null ? rows?.[state.selected]?.title : undefined)
      if (!clip) return
      void transport.take(clip).then((yes) => {
        if (!yes) return
        transport.seek(seconds)
        void transport.play()
      })
    },
    [session, meta.name, state.result, state.selected, rows],
  )

  const playingThis = !!state.result && t.loaded?.resultId === state.result.id

  const discs = useMemo(
    () =>
      session.members.map(({ tag, disc: d }) => {
        const how =
          d.identifiedBy === 'checksum'
            ? "identified by checksum: the data track's sha256 is in gamedb's table"
            : d.identifiedBy === 'serial'
              ? "identified by its own SYSTEM.CNF only"
              : 'not in gamedb'
        return (
          <Badge key={d.key} tone={d.identifiedBy === 'unrecognized' ? 'danger' : 'primary'} title={`${d.label}\n${how}`}>
            {d.identifiedBy === 'checksum' ? <BadgeCheck className="w-3 h-3" /> : <TriangleAlert className="w-3 h-3" />}
            {tag}
          </Badge>
        )
      }),
    [session.members],
  )

  const result = state.result
  const many = meta.discs.length > 1
  // the row the result shown is of, while its view's list is the one up
  const shownAt = state.shown?.split('|')
  const shownRow = shownAt && shownAt[0] === (state.view ?? '') ? (rows?.[Number(shownAt[1])] ?? null) : null

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      <div className="h-9 shrink-0 px-4 text-xs border-b border-border bg-accent/50 flex items-center gap-2.5">
        <Disc3 className="w-3.5 h-3.5 text-primary shrink-0" />
        <span className="font-medium truncate">{session.title}</span>
        {discs}
        {session.partial ? (
          <Badge tone="info" title={PARTIAL}>not fully supported yet</Badge>
        ) : (
          !session.plugin && <Badge tone="muted" title="No per-program decoders yet: only the PlayStation-generic tabs apply">generic tabs only</Badge>
        )}
        <span className="text-muted-foreground truncate font-mono text-[11px]">{session.status}</span>
        <div className="flex-1" />
        <button className="text-muted-foreground hover:text-foreground cursor-pointer" title="Close this game" onClick={onClose}>
          <X className="w-4 h-4" />
        </button>
      </div>
      <div className="flex-1 min-h-0 flex overflow-hidden">
        <ItemList
          key={meta.index}
          ref={listRef}
          tab={meta}
          view={state.view}
          rows={rows}
          loading={loadingItems}
          error={itemsError}
          selected={state.selected}
          onView={changeView}
          onSelect={(i) => void select(i)}
          onStep={(i) => {
            // Held arrow keys browse quickly: settle on a row before decoding it.
            window.clearTimeout(keyTimer.current)
            patch(meta.index, { selected: i })
            keyTimer.current = window.setTimeout(() => void select(i), 110)
          }}
          onActivate={(i) => {
            window.clearTimeout(keyTimer.current)
            void select(i, { play: true })
          }}
          onAbout={() => setAbout(true)}
          railMode={railMode}
        />
        <div className="flex-1 min-w-0 min-h-0 flex flex-col">
          {many && result && (
            <VersionBar
              result={result}
              onVersion={(v) => {
                setPrefer(result.versions[v][0])
                if (state.selected !== null) void select(state.selected, { version: v })
              }}
            />
          )}
          <PlaySongContext.Provider value={playSong}>
            <Stage
              sid={session.id}
              tab={meta}
              result={result}
              loading={!!state.selecting}
              error={state.selectError ?? null}
              playingThis={playingThis}
              onSeek={onSeek}
              railMode={railMode}
            />
          </PlaySongContext.Provider>
        </div>
        <Inspector session={session} tab={meta} result={state.result} row={shownRow} railMode={railMode} open={inspectorOpen} onToggle={toggleInspector} />
      </div>
      <CardHost session={session} railMode={railMode} onRailMode={onRailMode} playSong={playSong} />
      {about && (
        <Dialog title={`About: ${meta.name}`} onClose={() => setAbout(false)} className="w-[560px]">
          <AboutText tab={meta} advanced={railMode === 'advanced'} className="space-y-2 selectable" />
        </Dialog>
      )}
    </div>
  )
}

/** Which discs hold what is shown, and the switch between versions. */
function VersionBar({ result, onVersion }: { result: Result; onVersion: (v: number) => void }) {
  const several = result.versions.length > 1
  return (
    <div className="h-9 shrink-0 px-3 border-b border-border bg-card flex items-center gap-2 text-[11px]">
      {several ? (
        <>
          <span className="text-muted-foreground">Versions</span>
          <Segmented
            className="shrink-0 flex-nowrap"
            value={result.version}
            onChange={onVersion}
            options={result.versions.map((tags, i) => ({ value: i, label: tags.join(' · '), title: `As on ${tags.join(', ')}` }))}
          />
          <span className="text-muted-foreground truncate">the discs hold different contents</span>
        </>
      ) : (
        <span className="text-muted-foreground truncate">
          {result.tags.length > 1 ? `The same on ${result.tags.join(', ')}` : `From ${result.tags[0] ?? 'this disc'}`}
        </span>
      )}
    </div>
  )
}
