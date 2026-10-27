import { open } from '@tauri-apps/plugin-dialog'
import { getCurrentWindow } from '@tauri-apps/api/window'
import { RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Button } from './components/ui/button'
import { Dialog } from './components/ui/dialog'
import { Toaster, toast } from './components/ui/toast'
import { api, batchOf, indexing, poolRows, waitFor, type BatchDisc, type DiscRow, type Job, type Library, type Session, type Slot } from './lib/api'
import { ApiError, connect, inTauri, type BackendState } from './lib/backend'
import { spaceHandler } from './lib/keys'
import { railOrder, type RailMode } from './lib/tabs'
import { useStored } from './lib/hooks'
import { isAsking } from './lib/confirm'
import { isCardOpen, nav } from './lib/nav'
import { transport } from './lib/transport'
import { basename, forControl, inField, plural } from './lib/utils'
import { ConfirmHost } from './views/ConfirmHost'
import { DiscView } from './views/DiscView'
import { Importing, PathPrompt } from './views/Importing'
import { LibraryHome } from './views/LibraryHome'
import { Rail } from './views/Rail'
import { Setup } from './views/Setup'
import { Shortcuts } from './views/Shortcuts'
import { TransportBar } from './views/TransportBar'

type Mode = 'library' | 'disc'

const DISC_FILTERS = [
  { name: 'Disc images', extensions: ['cue', 'iso', 'bin'] },
  { name: 'All files', extensions: ['*'] },
]

/** What a toast says of the discs an extraction job extracted, every one it held. */
function extractedToast(discs: BatchDisc[], again: boolean): { title: string; body?: string } {
  if (discs.length === 1) {
    const d = discs[0]
    const note = d.recognized === false ? ' · identified by its SYSTEM.CNF only' : ''
    return again
      ? { title: `Re-extracted ${d.tag || d.serial}`, body: `${plural(d.files ?? 0, 'file')}${note}` }
      : { title: `Added ${d.tag || d.serial} to ${d.gameTitle}`, body: `${plural(d.files ?? 0, 'file')}${note}` }
  }
  const byGame = new Map<string, string[]>()
  for (const d of discs) byGame.set(d.gameTitle, [...(byGame.get(d.gameTitle) ?? []), d.tag || d.serial])
  const title = `${again ? 'Re-extracted' : 'Added'} ${plural(discs.length, 'disc')}`
  if (byGame.size === 1) {
    const [[game, tags]] = [...byGame]
    return { title: `${title} ${again ? 'of' : 'to'} ${game}`, body: tags.join(', ') }
  }
  return { title, body: [...byGame].map(([game, tags]) => `${game}: ${tags.join(', ')}`).join(' · ') }
}

export default function App() {
  const [backend, setBackend] = useState<BackendState>({ state: 'starting' })
  const [library, setLibrary] = useState<Library | null>(null)
  const [libraryError, setLibraryError] = useState<string | null>(null)
  const [mode, setMode] = useState<Mode>('library')
  const [session, setSession] = useState<Session | null>(null)
  const [tab, setTab] = useState(0)
  const [importing, setImporting] = useState<{ title: string; job: Job } | null>(null)
  /** Without the desktop shell: a path typed to add discs from, or to find a disc's image. */
  const [prompt, setPrompt] = useState<'add' | DiscRow | null>(null)
  const [confirm, setConfirm] = useState<DiscRow | null>(null)
  const [confirmGame, setConfirmGame] = useState<Slot | null>(null)
  /** The folder discs were last added from: where the folder dialog opens. */
  const [lastFolder, setLastFolder] = useStored<string>('import.folder', '')
  const [help, setHelp] = useState(false)
  const [opening, setOpening] = useState<string | null>(null)
  /** Choosing another library folder (the library's folder button). */
  const [switching, setSwitching] = useState(false)
  /** Fan mode or Advanced mode: which rail (docs/taxonomy.md). */
  const [railMode, setRailMode] = useStored<RailMode>('rail.mode', 'fan')

  const adoptBackend = useCallback((s: BackendState) => {
    setBackend(s)
    if (s.state === 'ready') {
      // Another library folder: nothing open survives it.
      setSwitching(false)
      setSession(null)
      setMode('library')
    }
  }, [])

  useEffect(() => {
    void connect().then(setBackend)
  }, [])

  const refresh = useCallback(async () => {
    try {
      setLibrary(await api.library())
      setLibraryError(null)
    } catch (e) {
      setLibraryError(e instanceof Error ? e.message : String(e))
    }
  }, [])

  useEffect(() => {
    if (backend.state === 'ready') void refresh()
  }, [backend, refresh])

  // While a disc is being indexed, the library screen shows how far.
  const indexingNow = library !== null && indexing(library)
  useEffect(() => {
    if (!indexingNow || mode !== 'library') return
    const timer = setInterval(() => void refresh(), 1000)
    return () => clearInterval(timer)
  }, [indexingNow, mode, refresh])

  // The transport plays on across tabs and the library page; only the
  // game it plays from closing (or another opening) stops it.
  useEffect(() => {
    const l = transport.state.loaded
    if (l && l.sessionId !== session?.id) transport.load(null)
  }, [session])

  // The window title says which game is open.
  useEffect(() => {
    const title = session && mode === 'disc' ? `Eternal Silver Asset Viewer — ${session.title}` : 'Eternal Silver Asset Viewer'
    document.title = title
    if (inTauri) void getCurrentWindow().setTitle(title).catch(() => {})
  }, [session, mode])

  // One open at a time: another asked for while one is on its way (a
  // double click) is dropped, so a slower reply cannot win.
  const openingNow = useRef(false)
  const openDisc = useCallback(async (key: string) => {
    if (openingNow.current) return
    openingNow.current = true
    setOpening(key)
    try {
      const s = await api.open(key)
      // Another game: a new history, now. Its view mounts, and goes to the
      // history's place, before the effect below that resets it runs.
      if (s.id !== session?.id) nav.reset()
      setSession(s)
      // a game opens on the first tab of the rail
      setTab(railOrder(s.tabs, railMode)[0]?.index ?? 0)
      setMode('disc')
    } catch (e) {
      toast({ tone: 'error', title: 'Could not open the game', body: e instanceof Error ? e.message : String(e) })
    } finally {
      openingNow.current = false
      setOpening(null)
    }
  }, [railMode, session])

  /**
   * Start an extraction job and follow it in the Importing dialog until
   * its extracting is over (the discs are indexed in the background
   * after: the library shows it). When every disc in it went in, the
   * dialog closes and says so; otherwise it stays, saying what was
   * skipped or failed, and why.
   */
  const extract = useCallback(
    async (title: string, start: () => Promise<Job>, again = false) => {
      setPrompt(null)
      let job: Job
      try {
        job = await start()
      } catch (e) {
        toast({ tone: 'error', title: again ? 'Could not re-extract' : 'Could not add discs', body: e instanceof Error ? e.message : String(e) })
        return
      }
      setImporting({ title, job })
      try {
        const done = await waitFor(job, (j) => setImporting({ title, job: j }), 250, 'index')
        if (done.state === 'error') return
        const discs = batchOf(done)
        const added = discs.filter((d) => d.state === 'added')
        if (added.length) {
          // A game open on a dump made again was closed with it; one open
          // gains a disc added the next time it opens.
          setSession(null)
          setMode('library')
        }
        await refresh()
        if (added.length && added.length === discs.length) {
          setImporting(null)
          toast({ tone: 'ok', ...extractedToast(added, again) })
        }
      } catch (e) {
        setImporting(null)
        toast({ tone: 'error', title: 'Extraction failed', body: e instanceof Error ? e.message : String(e) })
      }
    },
    [refresh],
  )

  /** A disc image, or a folder: every disc in it the library does not hold yet. */
  const addDiscs = useCallback(
    (path: string, title = `Adding ${basename(path)}`) => void extract(title, () => api.importDiscs(path)),
    [extract],
  )

  const chooseImage = useCallback(async () => {
    if (!inTauri) return setPrompt('add')
    const file = await open({ title: 'Select a PlayStation disc image', filters: DISC_FILTERS, defaultPath: library?.folder.discs ?? undefined })
    if (typeof file === 'string') addDiscs(file)
  }, [addDiscs, library])

  const chooseFolder = useCallback(async () => {
    if (!inTauri) return setPrompt('add')
    const folder = await open({ title: 'Choose a folder of PlayStation disc images', directory: true, defaultPath: lastFolder || library?.folder.discs || undefined })
    if (typeof folder !== 'string') return
    setLastFolder(folder)
    addDiscs(folder, `Adding discs from ${basename(folder)}`)
  }, [addDiscs, lastFolder, setLastFolder, library])

  /** A disc's image, found again after it moved: its dump is made from it. */
  const locate = useCallback(
    (disc: DiscRow, path: string) => void extract(`Re-extracting ${disc.label}`, () => api.reextract(disc.key, path), true),
    [extract],
  )

  const reextract = useCallback(
    async (disc: DiscRow) => {
      setConfirm(null)
      let job: Job
      try {
        job = await api.reextract(disc.key)
      } catch (e) {
        // The image moved: ask for it.
        if (e instanceof ApiError && e.extra.needsPath) {
          if (!inTauri) return setPrompt(disc)
          const file = await open({ title: `Locate the disc image for ${disc.label}`, filters: DISC_FILTERS })
          if (typeof file === 'string') locate(disc, file)
          return
        }
        toast({ tone: 'error', title: 'Could not re-extract', body: e instanceof Error ? e.message : String(e) })
        return
      }
      void extract(`Re-extracting ${disc.label}`, async () => job, true)
    },
    [extract, locate],
  )

  const reextractGame = useCallback(
    (slot: Slot) => {
      setConfirmGame(null)
      void extract(`Re-extracting ${slot.title}`, () => api.reextractGame(slot.key), true)
    },
    [extract],
  )

  // Another game: a new history of links followed.
  useEffect(() => {
    nav.reset()
  }, [session?.id])

  // Back and Forward through the links followed: Alt+← / Alt+→, and the
  // mouse's side buttons.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!e.altKey || e.ctrlKey || e.metaKey || e.shiftKey || isAsking() || inField(e)) return
      if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
        e.preventDefault()
        if (e.key === 'ArrowLeft') nav.back()
        else nav.forward()
      }
    }
    // buttons 3 and 4 are the side buttons: their press is kept from the
    // webview's own history, their release walks ours
    const onDown = (e: MouseEvent) => {
      if (e.button === 3 || e.button === 4) e.preventDefault()
    }
    const onUp = (e: MouseEvent) => {
      if ((e.button !== 3 && e.button !== 4) || isAsking()) return
      e.preventDefault()
      if (e.button === 3) nav.back()
      else nav.forward()
    }
    window.addEventListener('keydown', onKey)
    window.addEventListener('mousedown', onDown)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('mousedown', onDown)
      window.removeEventListener('mouseup', onUp)
    }
  }, [])

  // App-wide keys. The disc view handles its own (arrows, zoom, filter).
  // Space on a focused button presses it.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isAsking() || forControl(e)) return
      // [ and ] are typed with AltGr on many layouts (Ctrl+Alt, to Windows)
      // and with Option on a Mac: only Ctrl or Cmd as itself makes a chord.
      const bracket = e.key === '[' || e.key === ']'
      if (bracket ? (e.ctrlKey || e.metaKey) && !e.getModifierState('AltGraph') : e.ctrlKey || e.metaKey || e.altKey) return
      if (e.key === ' ') {
        e.preventDefault()
        const fn = spaceHandler()
        if (fn) fn()
        else transport.toggle()
      } else if (e.key === '?') setHelp(true)
      else if ((e.key === '[' || e.key === ']') && mode === 'disc' && session && !isCardOpen()) {
        const order = railOrder(session.tabs, railMode).map((t) => t.index)
        if (!order.length) return
        const at = order.indexOf(tab)
        const next = order[(at + (e.key === ']' ? 1 : order.length - 1)) % order.length]
        setTab(next)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [mode, session, tab, railMode])

  const ready = backend.state === 'ready'

  return (
    <div className="flex h-screen overflow-hidden">
      <Rail
        mode={mode}
        session={session}
        tab={tab}
        railMode={railMode}
        onRailMode={setRailMode}
        onLibrary={() => {
          setMode('library')
          void refresh()
        }}
        onTab={(i) => {
          setTab(i)
          setMode('disc')
        }}
        onHelp={() => setHelp(true)}
      />
      {!ready || switching ? (
        <Setup
          state={backend}
          choosing={switching}
          current={library?.folder.path}
          onState={adoptBackend}
          onCancel={switching ? () => setSwitching(false) : undefined}
        />
      ) : (
        <div className="flex-1 min-w-0 flex flex-col overflow-hidden">
          <TransportBar railMode={railMode} />
          {mode === 'disc' && session ? (
            <DiscView
              key={session.id}
              session={session}
              tab={tab}
              railMode={railMode}
              onTab={setTab}
              onRailMode={setRailMode}
              onClose={() => {
                setMode('library')
                setSession(null)
                // Closed, not just left for the library (which keeps it, to
                // come back to): the backend lets its discs go, so a movie
                // played no longer holds the disc image open.
                void api.close(session.id).catch(() => {})
              }}
            />
          ) : library ? (
            <LibraryHome
              library={library}
              opening={opening}
              onOpen={(key) => void openDisc(key)}
              onAdd={() => void chooseImage()}
              onAddFolder={() => void chooseFolder()}
              onExtract={addDiscs}
              onReextract={setConfirm}
              onReextractGame={setConfirmGame}
              onChooseFolder={() => setSwitching(true)}
              onRefresh={() => void refresh()}
            />
          ) : (
            <div className="flex-1 flex items-center justify-center p-8">
              {libraryError ? (
                <div className="max-w-md rounded-lg border border-border bg-card p-5 space-y-3">
                  <p className="text-sm font-medium">The backend is not answering</p>
                  <p className="text-xs font-mono text-muted-foreground break-words">{libraryError}</p>
                  <Button size="sm" onClick={() => void connect().then(setBackend)}>
                    <RefreshCw className="w-3.5 h-3.5" /> Retry
                  </Button>
                </div>
              ) : (
                <p className="text-xs text-muted-foreground">Reading the library…</p>
              )}
            </div>
          )}
          {opening && (
            <div className="fixed bottom-4 left-1/2 -translate-x-1/2 rounded-md bg-card border border-border shadow px-3 py-2 text-xs">Opening {opening}…</div>
          )}
        </div>
      )}
      {importing && <Importing title={importing.title} job={importing.job} onClose={() => setImporting(null)} />}
      {prompt === 'add' && (
        <PathPrompt
          title="Add discs"
          action="Add"
          placeholder="/path/to/disc.cue, or a folder of disc images"
          pool={library ? poolRows(library) : []}
          onPick={addDiscs}
          onClose={() => setPrompt(null)}
        />
      )}
      {prompt && prompt !== 'add' && (
        <PathPrompt
          title={`Locate the disc image for ${prompt.label}`}
          action="Re-extract"
          placeholder="/path/to/disc.cue"
          onPick={(p) => locate(prompt, p)}
          onClose={() => setPrompt(null)}
        />
      )}
      {confirmGame && (
        <Dialog title="Re-extract every disc of this game?" onClose={() => setConfirmGame(null)}>
          <p className="text-xs text-secondary-foreground">{confirmGame.title}</p>
          <p className="text-xs text-muted-foreground mt-2">
            Each of its {plural(confirmGame.present, 'extracted disc')} is extracted again from the image it came from, one after another, and replaces its dump in the
            library. A disc whose image has moved is skipped.
          </p>
          <div className="flex justify-end gap-2 mt-4">
            <Button size="sm" variant="outline" onClick={() => setConfirmGame(null)}>
              Cancel
            </Button>
            <Button size="sm" variant="destructive" onClick={() => reextractGame(confirmGame)}>
              Re-extract all
            </Button>
          </div>
        </Dialog>
      )}
      {confirm && (
        <Dialog title="Re-extract this disc?" onClose={() => setConfirm(null)}>
          <p className="text-xs text-secondary-foreground">{confirm.label}</p>
          <p className="text-xs text-muted-foreground mt-2">
            Its dump, <span className="font-mono">{confirm.key}/</span> in the library, is replaced by a fresh extraction of the image it came from.
          </p>
          <div className="flex justify-end gap-2 mt-4">
            <Button size="sm" variant="outline" onClick={() => setConfirm(null)}>
              Cancel
            </Button>
            <Button size="sm" variant="destructive" onClick={() => void reextract(confirm)}>
              Re-extract
            </Button>
          </div>
        </Dialog>
      )}
      {help && <Shortcuts onClose={() => setHelp(false)} />}
      <ConfirmHost />
      <Toaster />
    </div>
  )
}
