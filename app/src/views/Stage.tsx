import { LoaderCircle, MousePointerClick, Pause, Play, TriangleAlert } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Extended } from '../components/Extended'
import { Segmented } from '../components/ui/segmented'
import { toast } from '../components/ui/toast'
import { api, type Result, type Scene, type TabMeta } from '../lib/api'
import { TAB_BLURB, tabIcon, type RailMode } from '../lib/tabs'
import { songsOf } from '../lib/songs'
import { transport, useTransport } from '../lib/transport'
import { basename, cn } from '../lib/utils'
import { ArrangementView } from './stage/ArrangementView'
import { BromideView } from './stage/BromideView'
import { SummaryView } from './stage/SummaryView'
import { FieldSceneView } from './stage/FieldSceneView'
import { PixelView } from './stage/PixelView'
import { SceneView } from './stage/SceneView'
import { SheetView } from './stage/SheetView'
import { SongButtons } from './stage/SongButtons'
import { TableView } from './stage/TableView'
import { TextView } from './stage/TextView'
import { VideoView } from './stage/VideoView'
import { WaveformView } from './stage/WaveformView'

/** Does this result fill the stage with pixels (its text then goes to the inspector)? */
export function isPictorial(r: Result | null): boolean {
  return !!r && (!!r.video || !!r.scene || !!r.frames || !!r.layers?.length)
}

/**
 * The middle of the window: whatever the selection IS. Pixels, frames and
 * movies take the whole stage; everything else is a column of documents —
 * a timeline or waveform first, then any summary, table and text.
 */
export function Stage({
  sid,
  tab,
  result,
  loading,
  error,
  playingThis,
  onSeek,
  railMode,
}: {
  sid: string
  tab: TabMeta
  result: Result | null
  loading: boolean
  error: string | null
  /** The transport holds this result's clip. */
  playingThis: boolean
  onSeek: (seconds: number) => void
  /** A page's extended info is folded in Fan mode, open in Advanced. */
  railMode: RailMode
}) {
  // A map draws itself after its result is in, from pictures it loads
  // (FieldSceneView): the stage is still decoding until its first frame.
  const [drawn, setDrawn] = useState<Scene | null>(null)
  const busy = loading || (!error && !!result?.scene?.field && drawn !== result.scene)
  const [slow, setSlow] = useState(false)
  useEffect(() => {
    if (!busy) return setSlow(false)
    const id = setTimeout(() => setSlow(true), 350)
    return () => clearTimeout(id)
  }, [busy])

  const exportPng = async (layer: number, all: boolean) => {
    if (!result) return
    try {
      const { paths } = await api.export(sid, result.id, 'png', layer, all)
      toast({
        tone: 'ok',
        title: paths.length > 1 ? `Exported ${paths.length} images` : `Exported ${basename(paths[0])}`,
        body: paths.length > 1 ? `${basename(paths[0])} … ${basename(paths[paths.length - 1])}` : paths[0],
        action: { label: 'Show in folder', run: () => void api.reveal(paths[0]) },
      })
    } catch (e) {
      toast({ tone: 'error', title: 'Export failed', body: e instanceof Error ? e.message : String(e) })
    }
  }

  let body
  if (error) body = <Problem message={error} />
  else if (!result) body = loading ? <div className="flex-1" /> : <About tab={tab} advanced={railMode === 'advanced'} />
  else if (result.video) body = <VideoView key={result.video.id} sid={sid} video={result.video} label={result.label} />
  else if (result.scene?.field)
    body = (
      <FieldSceneView
        key={result.id}
        scene={result.scene}
        stills={result.layers ?? []}
        onExport={exportPng}
        memory={tab.key}
        actions={songsOf(result).length ? <SongButtons result={result} /> : undefined}
        title={result.label.trim().split(/\s{2,}/).slice(0, 2).join(' · ')}
        disc={result.disc}
        onSave={(name, png, scale) => api.save(sid, result.id, name, png, scale).then((r) => r.path)}
        onDrawn={setDrawn}
        advanced={railMode === 'advanced'}
      />
    )
  else if (result.scene)
    body = (
      <SceneView
        key={result.id}
        scene={result.scene}
        stills={result.layers ?? []}
        onExport={exportPng}
        memory={tab.key}
        actions={songsOf(result).length ? <SongButtons result={result} /> : undefined}
        advanced={railMode === 'advanced'}
      />
    )
  else if (result.frames)
    body = (
      <PixelView
        picture={{
          layers: result.frames.blobs.map((b, i) => ({ blob: b, label: `frame ${i}`, w: result.frames!.w, h: result.frames!.h })),
          animate: { intervalMs: result.frames.intervalMs },
        }}
        grid={false}
        onExport={exportPng}
        memory={tab.key}
      />
    )
  else if (result.pan)
    body = <BromideView key={result.id} result={result} pan={result.pan} advanced={railMode === 'advanced'} onExport={exportPng} />
  else if (result.layers?.length) body = <PixelView picture={{ layers: result.layers }} grid={tab.supportsGrid} onExport={exportPng} memory={tab.key} />
  else body = <Documents result={result} playingThis={playingThis} onSeek={onSeek} advanced={railMode === 'advanced'} />

  return (
    <div className="flex-1 min-w-0 min-h-0 flex flex-col relative">
      {busy && (
        <div className="absolute top-0 inset-x-0 h-0.5 z-20 overflow-hidden">
          <div className="h-full w-1/3 bg-primary animate-slide" />
        </div>
      )}
      {busy && slow && (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-background/40 pointer-events-none">
          <div className="rounded-md bg-card border border-border shadow px-3 py-2 text-xs flex items-center gap-2">
            <LoaderCircle className="w-3.5 h-3.5 animate-spin text-primary" /> Decoding…
          </div>
        </div>
      )}
      {body}
    </div>
  )
}

function Documents({ result, playingThis, onSeek, advanced }: { result: Result; playingThis: boolean; onSeek: (s: number) => void; advanced: boolean }) {
  const [mode, setMode] = useState<'table' | 'text'>('table')
  const hasTable = !!result.table && result.table.columns.length > 0
  const showTable = hasTable && (mode === 'table' || result.text === undefined)
  const fills = showTable || result.text !== undefined
  const nothing = !result.sheet && !result.arrangement && !result.waveform && !result.summary && !hasTable && result.text === undefined
  const sound = (
    <>
      {result.arrangement && <ArrangementView data={result.arrangement} active={playingThis} onSeek={onSeek} />}
      {result.waveform && <WaveformView waveform={result.waveform} active={playingThis} onSeek={onSeek} />}
    </>
  )
  // a page that says where its sound goes (a song's: under its title) has it there
  const soundInSheet = !!result.sheet?.sections.some((s) => s.sound)

  return (
    <div className={cn('flex-1 min-h-0 overflow-auto p-4 flex flex-col gap-4', !fills && 'items-stretch')}>
      {result.sheet && (
        <SheetView
          sheet={result.sheet}
          disc={result.disc}
          advanced={advanced}
          sound={
            soundInSheet && (
              <div className="space-y-2">
                <PlayButton playingThis={playingThis} onSeek={onSeek} />
                {sound}
              </div>
            )
          }
        />
      )}
      {!soundInSheet && sound}
      {result.summary && <SummaryView title={result.summary.title} fields={result.summary.fields} className={cn(!result.waveform && 'max-w-2xl')} />}
      {hasTable && result.text !== undefined && (
        <Segmented
          className="w-56"
          value={mode}
          onChange={setMode}
          options={[
            { value: 'table', label: 'Table' },
            { value: 'text', label: 'Text + raw bytes' },
          ]}
        />
      )}
      {showTable ? (
        <TableView columns={result.table!.columns} rows={result.table!.rows} groups={result.table!.groups} notes={result.table!.notes} />
      ) : (
        result.text !== undefined && <TextView text={advanced ? result.text : (result.fanText ?? result.text)} wrap={result.textWrap ?? true} />
      )}
      {nothing && (
        <div className="max-w-xl rounded-lg border border-dashed border-border bg-card p-5">
          <p className="text-sm font-medium">Nothing to render</p>
          <p className="text-xs text-muted-foreground mt-1 whitespace-pre-wrap selectable">
            {result.info || 'This entry has no image layers.'}
          </p>
        </div>
      )}
    </div>
  )
}

/** Play the page's sound on the transport (asking first while another
 *  plays), or pause and resume it once it is the transport's. */
function PlayButton({ playingThis, onSeek }: { playingThis: boolean; onSeek: (s: number) => void }) {
  const t = useTransport()
  const playing = playingThis && t.playing
  const Icon = playing ? Pause : Play
  return (
    <button
      className="h-8 px-3 rounded-md bg-primary text-primary-foreground text-xs flex items-center gap-1.5 cursor-pointer hover:bg-primary/90"
      title={playing ? 'Pause (Space)' : playingThis ? 'Play (Space)' : 'Play it on the transport'}
      onClick={() => (playingThis ? transport.toggle() : onSeek(0))}
    >
      <Icon className="w-3.5 h-3.5" /> {playing ? 'Pause' : 'Play'}
    </button>
  )
}

/** Paragraphs, split by a blank line; a line break inside one is a space. */
function paragraphs(text: string): string[] {
  return text
    .split(/\n\s*\n/)
    .map((p) => p.replace(/\s*\n\s*/g, ' ').trim())
    .filter(Boolean)
}

/**
 * What a tab holds: in Fan mode its words for a fan (`fanAbout`), and how
 * the viewer reads it folded under them; in Advanced mode how it reads it.
 * A tab with no words for a fan says how it reads it in both.
 */
export function AboutText({ tab, advanced, className }: { tab: TabMeta; advanced: boolean; className?: string }) {
  const how = paragraphs(tab.about || TAB_BLURB[tab.key] || 'No description.')
  const said = (paras: string[]) =>
    paras.map((p, i) => (
      <p key={i} className="text-xs leading-relaxed text-secondary-foreground selectable">
        {p}
      </p>
    ))
  if (advanced || !tab.fanAbout) return <div className={className}>{said(how)}</div>
  return (
    <div className={className}>
      {said(paragraphs(tab.fanAbout))}
      <Extended key="fan" advanced={false} title="How the viewer reads it" className="pt-1">
        <div className="space-y-3">{said(how)}</div>
      </Extended>
    </div>
  )
}

function About({ tab, advanced }: { tab: TabMeta; advanced: boolean }) {
  const Icon = tabIcon(tab.key)
  return (
    <div className="flex-1 overflow-auto p-8 flex justify-center items-start">
      <div className="max-w-xl w-full rounded-lg border border-border bg-card shadow-sm p-6 space-y-3 animate-fade-in">
        <div className="flex items-center gap-3">
          <span className="w-9 h-9 rounded-md bg-accent text-primary flex items-center justify-center">
            <Icon className="w-5 h-5" />
          </span>
          <div>
            <h2 className="font-semibold">{tab.name}</h2>
            <p className="text-xs text-muted-foreground flex items-center gap-1">
              <MousePointerClick className="w-3 h-3" /> Pick an entry on the left — ↑/↓ browse, double-click or Enter plays
            </p>
          </div>
        </div>
        <AboutText tab={tab} advanced={advanced} className="space-y-3" />
      </div>
    </div>
  )
}

function Problem({ message }: { message: string }) {
  return (
    <div className="flex-1 flex items-center justify-center p-8">
      <div className="max-w-lg rounded-lg border border-destructive/30 bg-card shadow-sm p-5 flex gap-3">
        <TriangleAlert className="w-5 h-5 text-destructive shrink-0" />
        <div>
          <p className="text-sm font-medium">This entry could not be shown</p>
          <p className="text-xs text-muted-foreground font-mono mt-1 break-words selectable">{message}</p>
        </div>
      </div>
    </div>
  )
}
