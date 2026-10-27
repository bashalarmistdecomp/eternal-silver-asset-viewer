import { open } from '@tauri-apps/plugin-dialog'
import { FolderOpen, LoaderCircle, RotateCw, TriangleAlert } from 'lucide-react'
import { useState } from 'react'
import { Button } from '../components/ui/button'
import { restartBackend, setLibrary, type BackendState } from '../lib/backend'

/**
 * What shows instead of the library: the backend starting, the backend
 * failing, or (`choosing`) the person picking another library folder. The
 * library is one folder holding the discs and everything extracted from
 * them; with none chosen the backend uses its default one.
 */
export function Setup({
  state,
  choosing,
  current,
  onState,
  onCancel,
}: {
  state: BackendState
  choosing: boolean
  /** The folder in use, when there is one. */
  current?: string
  onState: (s: BackendState) => void
  onCancel?: () => void
}) {
  const [busy, setBusy] = useState(false)
  // What the shell refused (a folder it cannot use, settings it cannot
  // save): the backend that ran runs on, and this says why nothing changed.
  const [refused, setRefused] = useState<string | null>(null)
  const run = async (step: () => Promise<BackendState>, what: string) => {
    setBusy(true)
    setRefused(null)
    try {
      onState(await step())
    } catch (e) {
      setRefused(`${what}: ${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setBusy(false)
    }
  }
  const choose = async () => {
    let dir: string | string[] | null
    try {
      dir = await open({ directory: true, title: 'Choose a library folder', defaultPath: current })
    } catch (e) {
      setRefused(`Could not show the folder dialog: ${e instanceof Error ? e.message : String(e)}`)
      return
    }
    if (typeof dir === 'string') await run(() => setLibrary(dir), 'Could not use that folder')
  }

  if (state.state === 'starting' && !choosing)
    return (
      <div className="flex-1 flex items-center justify-center">
        <p className="text-xs text-muted-foreground flex items-center gap-2">
          <LoaderCircle className="w-4 h-4 animate-spin text-primary" /> Starting the backend…
        </p>
      </div>
    )

  // A backend that failed says so, and how, while choosing another folder too.
  const failed = state.state === 'error'
  return (
    <div className="flex-1 flex items-center justify-center p-8">
      <div className="w-[560px] rounded-lg border border-border bg-card shadow-sm p-6 space-y-4">
        <div className="flex items-center gap-3">
          {failed ? <TriangleAlert className="w-8 h-8 text-destructive shrink-0" /> : <FolderOpen className="w-8 h-8 text-primary shrink-0" />}
          <div>
            <h1 className="text-lg font-semibold">{failed ? 'The backend did not start' : 'Choose a library folder'}</h1>
            <p className="text-xs text-muted-foreground">
              {failed
                ? state.message
                : 'The library holds the disc images you add and everything extracted from them, one folder per program. Choose a folder with room for it: an extracted disc takes about as much space as its image.'}
            </p>
            {!failed && current && <p className="text-[11px] font-mono text-muted-foreground mt-1 break-all">Now: {current}</p>}
          </div>
        </div>
        {refused && <p className="text-xs text-destructive break-words">{refused}</p>}
        {failed && state.log.length > 0 && (
          <pre className="max-h-56 overflow-auto rounded-md bg-stage text-stage-foreground text-[10px] leading-relaxed p-3 font-mono whitespace-pre-wrap selectable">
            {state.log.join('\n')}
          </pre>
        )}
        <div className="flex gap-2">
          <Button onClick={() => void choose()} disabled={busy}>
            <FolderOpen className="w-4 h-4" /> Choose folder…
          </Button>
          {failed && (
            <Button variant="outline" onClick={() => void run(restartBackend, 'Could not restart the backend')} disabled={busy}>
              <RotateCw className="w-4 h-4" /> Try again
            </Button>
          )}
          {choosing && (
            <Button variant="outline" onClick={() => void run(() => setLibrary(null), 'Could not use the default folder')} disabled={busy}>
              Use the default folder
            </Button>
          )}
          {onCancel && (
            <Button variant="ghost" onClick={onCancel} disabled={busy}>
              Cancel
            </Button>
          )}
        </div>
        <p className="text-[11px] text-muted-foreground border-t border-border pt-3">
          The app runs its own backend, bundled with it (a development build runs{' '}
          <span className="font-mono">backend/server.py</span> with the repository’s{' '}
          <span className="font-mono">.venv</span>). It listens on 127.0.0.1 only.
        </p>
      </div>
    </div>
  )
}
