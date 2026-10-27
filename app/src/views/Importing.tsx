import { CircleCheck, CircleDashed, CircleMinus, CircleX, LoaderCircle, TriangleAlert } from 'lucide-react'
import { useState } from 'react'
import { Button } from '../components/ui/button'
import { Dialog } from '../components/ui/dialog'
import { batchOf, extracted, type BatchDisc, type Job, type PoolRow } from '../lib/api'
import { cn, fmtBytes, plural } from '../lib/utils'

/**
 * An extraction job: the disc images it extracts one after another (a
 * folder's new discs, one image, a disc or a game's discs made again),
 * each said to be extracted or failed as it goes, and the ones it skips,
 * and why. It can be closed once the extracting is over: the indexing
 * that follows shows in the library.
 */
export function Importing({ title, job, onClose }: { title: string; job: Job; onClose: () => void }) {
  const over = extracted(job)
  const discs = batchOf(job)
  const todo = discs.filter((d) => d.state !== 'skipped')
  const skipped = discs.filter((d) => d.state === 'skipped')
  return (
    <Dialog title={title} onClose={over ? onClose : () => {}} className="w-[560px]">
      <div className="space-y-3">
        {job.state === 'error' ? (
          <Failure text={job.error} />
        ) : discs.length === 0 ? (
          over ? (
            <p className="text-xs text-muted-foreground">No disc images there (.cue, .iso or .bin).</p>
          ) : (
            <Working message={job.message || 'Looking for disc images…'} />
          )
        ) : (
          <>
            <p className="text-xs text-muted-foreground">{summary(todo, skipped, over)}</p>
            {todo.length > 0 && (
              <ul className="divide-y divide-border/70 rounded-md border border-border">
                {todo.map((d) => (
                  <Row key={d.path} disc={d} job={job} />
                ))}
              </ul>
            )}
            {skipped.length > 0 && (
              <div className="space-y-1">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Skipped</p>
                <ul className="space-y-1">
                  {skipped.map((d) => (
                    <li key={d.path} className="flex items-start gap-2 text-[11px] text-muted-foreground" title={d.path}>
                      <CircleMinus className="w-3.5 h-3.5 shrink-0 mt-px" />
                      <span className="min-w-0">
                        <span className="text-secondary-foreground">{d.tag ? `${d.tag} · ${d.label}` : d.label}</span> — {d.why}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
        {over && (
          <div className="flex justify-end">
            <Button size="sm" onClick={onClose}>
              Close
            </Button>
          </div>
        )}
      </div>
    </Dialog>
  )
}

/** "Extracting disc 2 of 4 · 7 skipped", and when it is over what became of them. */
function summary(todo: BatchDisc[], skipped: BatchDisc[], over: boolean): string {
  const parts: string[] = []
  if (over) {
    const done = todo.filter((d) => d.state === 'added').length
    const failed = todo.filter((d) => d.state === 'failed').length
    parts.push(todo.length ? `${plural(done, 'disc')} extracted` : 'Nothing new to extract')
    if (failed) parts.push(`${failed} failed`)
  } else if (todo.length) {
    const at = todo.findIndex((d) => d.state === 'extracting' || d.state === 'waiting')
    parts.push(todo.length === 1 ? 'Extracting' : `Extracting disc ${at < 0 ? todo.length : at + 1} of ${todo.length}`)
  }
  if (skipped.length) parts.push(`${skipped.length} skipped`)
  return parts.join(' · ')
}

function Row({ disc: d, job }: { disc: BatchDisc; job: Job }) {
  return (
    <li className="px-3 py-2 flex items-start gap-2.5" title={d.path}>
      <StateIcon state={d.state} />
      <div className="flex-1 min-w-0 space-y-0.5">
        <p className="text-xs truncate">
          {d.tag && <span className="font-semibold text-primary">{d.tag} · </span>}
          {d.label}
        </p>
        {d.state === 'extracting' ? (
          <Progress job={job} />
        ) : d.state === 'failed' ? (
          <p className="text-[11px] text-destructive break-words selectable">{d.why}</p>
        ) : d.state === 'added' ? (
          <p className="text-[11px] text-muted-foreground">
            extracted · {plural(d.files ?? 0, 'file')}
            {d.recognized === false && ' · identified by its SYSTEM.CNF only'}
          </p>
        ) : (
          <p className="text-[11px] text-muted-foreground">waiting</p>
        )}
      </div>
    </li>
  )
}

function StateIcon({ state }: { state: BatchDisc['state'] }) {
  const cls = 'w-4 h-4 shrink-0'
  if (state === 'extracting') return <LoaderCircle className={cn(cls, 'animate-spin text-primary')} />
  if (state === 'added') return <CircleCheck className={cn(cls, 'text-ok')} />
  if (state === 'failed') return <CircleX className={cn(cls, 'text-destructive')} />
  if (state === 'skipped') return <CircleMinus className={cn(cls, 'text-muted-foreground')} />
  return <CircleDashed className={cn(cls, 'text-muted-foreground')} />
}

/** The disc being extracted: DiscExtractor's own messages, as it reports them. */
function Progress({ job }: { job: Job }) {
  const pct = job.total ? Math.min(100, (100 * job.current) / job.total) : null
  return (
    <div className="space-y-1">
      <div className="h-1.5 bg-secondary rounded-full overflow-hidden">
        <div className="h-full bg-primary transition-[width]" style={{ width: `${pct ?? 8}%` }} />
      </div>
      <p className="text-[11px] text-muted-foreground truncate">{job.message || 'Starting…'}</p>
    </div>
  )
}

function Working({ message }: { message: string }) {
  return (
    <p className="text-xs text-muted-foreground flex items-center gap-2 truncate">
      <LoaderCircle className="w-3.5 h-3.5 animate-spin text-primary shrink-0" />
      <span className="truncate">{message}</span>
    </p>
  )
}

function Failure({ text }: { text: string }) {
  return (
    <div className="flex gap-2">
      <TriangleAlert className="w-4 h-4 text-destructive shrink-0 mt-0.5" />
      <p className="text-xs text-destructive break-words selectable">{text}</p>
    </div>
  )
}

/**
 * Without the desktop shell there is no native file dialog: type a path
 * (a disc image, or a folder of them where `pool` is given), or pick an
 * image the library already has in its discs/ folder.
 */
export function PathPrompt({
  title,
  action,
  placeholder,
  pool,
  onPick,
  onClose,
}: {
  title: string
  action: string
  placeholder: string
  pool?: PoolRow[]
  onPick: (path: string) => void
  onClose: () => void
}) {
  const [path, setPath] = useState('')
  return (
    <Dialog title={title} onClose={onClose} className="w-[560px]">
      <div className="space-y-3">
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            if (path.trim()) onPick(path.trim())
          }}
        >
          <input
            autoFocus
            value={path}
            onChange={(e) => setPath(e.target.value)}
            placeholder={placeholder}
            className="flex-1 h-8 rounded-md border border-input bg-background px-2 text-xs font-mono outline-none focus:border-primary"
          />
          <Button size="sm" type="submit" disabled={!path.trim()}>
            {action}
          </Button>
        </form>
        {pool && pool.length > 0 && (
          <div className="space-y-1">
            <p className="text-[11px] text-muted-foreground">Or one already in the library's discs/:</p>
            {pool.map((r) => (
              <button key={r.path} onClick={() => onPick(r.path)} className="w-full text-left rounded-md border border-border px-2.5 py-1.5 hover:border-primary cursor-pointer">
                <span className="text-xs font-medium">{r.title}</span>
                <span className="block text-[10px] font-mono text-muted-foreground">
                  {[r.serial, fmtBytes(r.bytes)].filter(Boolean).join(' · ')}
                </span>
              </button>
            ))}
          </div>
        )}
      </div>
    </Dialog>
  )
}
