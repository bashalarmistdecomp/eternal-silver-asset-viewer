import { Download, Pause, Play, Repeat, SkipBack, Square } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Button } from '../components/ui/button'
import { Dialog } from '../components/ui/dialog'
import { toast } from '../components/ui/toast'
import { api } from '../lib/api'
import { KindIcon } from '../components/RefLink'
import type { RailMode } from '../lib/tabs'
import { transport, useTransport, type Loaded } from '../lib/transport'
import { basename, cn, formatTime } from '../lib/utils'

/**
 * Always present, so the layout does not shift as selections change; the
 * controls grey out when nothing is loaded. The loaded track is global: it
 * plays on across tabs, and a list loads its own track only after asking
 * while another plays (lib/transport.ts). A score plays live and repeats
 * its endless loop while the loop switch is on; its time is shown on the
 * score's map, with the part playing beside it (intro, loop pass n,
 * ending). Export saves the loaded track, as WAV or MIDI. A song is named
 * by its title first, a sound effect by its number ("sound effect 9"),
 * a voice by who says what, each with its kind's icon; in Fan mode a clip
 * with no title of its own leads with its entry's. With nothing loaded,
 * Fan mode points at Music.
 */
export function TransportBar({ railMode }: { railMode: RailMode }) {
  const t = useTransport()
  const loaded = t.loaded
  const songs = loaded?.clip.songs ?? []
  const songTitle = loaded?.clip.title ?? loaded?.title
  // an untitled song's title is its number already
  const numbers = songs.map((n) => `song ${n}`).filter((s) => s !== songTitle)
  // what the clip is, by its kind's icon: a song, a sound effect
  const kind = loaded?.clip.kind ?? (songs.length ? 'song' : null)
  const kindMark = kind && <KindIcon kind={kind} className="w-3.5 h-3.5 inline -mt-0.5 mr-1.5 text-primary" />
  const timeRef = useRef<HTMLSpanElement>(null)
  const partRef = useRef<HTMLSpanElement>(null)
  const fillRef = useRef<HTMLDivElement>(null)
  const barRef = useRef<HTMLDivElement>(null)
  const [exporting, setExporting] = useState(false)

  // The readout and the fill tick with the media clock, not with React.
  useEffect(() => {
    let raf = 0
    const tick = () => {
      const pos = transport.position()
      const dur = transport.state.duration
      if (timeRef.current) timeRef.current.textContent = formatTime(pos)
      if (partRef.current) partRef.current.textContent = transport.part()
      if (fillRef.current) fillRef.current.style.width = `${dur > 0 ? Math.min(100, (pos / dur) * 100) : 0}%`
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [])

  const seekAt = (clientX: number) => {
    const el = barRef.current
    if (!el || !t.duration) return
    const r = el.getBoundingClientRect()
    transport.seek(((clientX - r.left) / r.width) * t.duration)
  }

  const playable = !!(loaded?.clip.wav || loaded?.clip.live)
  const loop = loaded?.clip.loop ?? null

  return (
    <div className="h-11 shrink-0 bg-card border-b border-border flex items-center gap-1 px-3">
      <Button variant="ghost" size="icon" title="Back to start" disabled={!playable} onClick={() => transport.seek(0)}>
        <SkipBack className="w-3.5 h-3.5" />
      </Button>
      <Button variant="ghost" size="icon" title="Stop" disabled={!playable} onClick={() => transport.stop()}>
        <Square className="w-3.5 h-3.5" />
      </Button>
      <Button variant="ghost" size="iconLg" className="text-primary" title="Play / pause (Space)" disabled={!playable} onClick={() => transport.toggle()}>
        {t.playing ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
      </Button>
      <div className="h-5 border-l border-border mx-1" />
      <div className="font-mono text-xs w-[118px] shrink-0">
        <span ref={timeRef}>0:00.0</span>
        <span className="text-muted-foreground"> / {formatTime(t.duration)}</span>
      </div>
      {loop && <span ref={partRef} className="font-mono text-[10px] text-muted-foreground w-11 shrink-0 truncate" title="The part of the score playing" />}
      <div
        ref={barRef}
        className={cn('relative h-1.5 w-56 max-w-[24vw] rounded-full bg-secondary shrink', playable && 'cursor-pointer')}
        onPointerDown={(e) => {
          if (!playable) return
          e.currentTarget.setPointerCapture(e.pointerId)
          seekAt(e.clientX)
        }}
        onPointerMove={(e) => e.buttons === 1 && playable && seekAt(e.clientX)}
        title={playable ? 'Seek' : undefined}
      >
        <div ref={fillRef} className="absolute inset-y-0 left-0 rounded-full bg-primary" style={{ width: 0 }} />
        {loop && t.duration > 0 && (
          <div
            className={cn('absolute -inset-y-0.5 rounded-sm border pointer-events-none', t.looping ? 'border-amber-500' : 'border-border')}
            style={{ left: `${(loop[0] / t.duration) * 100}%`, width: `${((loop[1] - loop[0]) / t.duration) * 100}%` }}
          />
        )}
      </div>
      <Button
        variant={t.looping && loop ? 'secondary' : 'ghost'}
        size="icon"
        className={cn('ml-1', t.looping && loop && 'text-primary')}
        title={
          loop
            ? t.looping
              ? `Loop on: ${formatTime(loop[0])}–${formatTime(loop[1])} repeats as the game repeats it. Click to play on into the ending.`
              : 'Loop off: plays on into the ending. Click to repeat the loop as the game does.'
            : 'No endless loop in this clip'
        }
        disabled={!loop}
        onClick={() => transport.setLooping(!t.looping)}
      >
        <Repeat className="w-3.5 h-3.5" />
      </Button>
      <div className="h-5 border-l border-border mx-2" />
      <div className="flex-1 min-w-0 flex items-center gap-2">
        {loaded && songs.length ? (
          <span className="text-xs truncate" title={`${loaded.source} · ${loaded.clip.name}`}>
            {kindMark}
            <span className="font-medium">{songTitle}</span>
            {numbers.length > 0 && <span className="text-muted-foreground"> · {numbers.join(', ')}</span>}
          </span>
        ) : loaded && (loaded.clip.title || railMode === 'fan') ? (
          <span className="text-xs truncate" title={`${loaded.source} · ${loaded.clip.name}`}>
            {kindMark}
            <span className="font-medium">{loaded.clip.title ?? loaded.title}</span>
            <span className="text-muted-foreground"> · {loaded.source.split(' · ')[0]}</span>
          </span>
        ) : loaded ? (
          <span className="text-xs truncate" title={loaded.source}>
            <span className="font-medium font-mono">{loaded.clip.name}</span>
            <span className="text-muted-foreground"> · {loaded.source}</span>
          </span>
        ) : (
          <span className="text-xs text-muted-foreground truncate">
            {railMode === 'fan'
              ? "Nothing playing — pick a song in Music, or play a map's music"
              : "No clip — select a song, sample, bank, sequence or CD track, or play a map's music"}
          </span>
        )}
        {t.error && (
          <button className="text-[11px] text-destructive truncate cursor-pointer" title={t.error} onClick={() => transport.clearError()}>
            {t.error}
          </button>
        )}
      </div>
      <div className="h-5 border-l border-border mx-1" />
      <Button
        variant="ghost"
        size="sm"
        className="h-7 text-[11px] gap-1 shrink-0"
        disabled={!loaded || (!playable && !loaded.clip.midi)}
        onClick={() => setExporting(true)}
        title="Export the clip"
      >
        <Download className="w-3.5 h-3.5" /> Export
      </Button>
      <span
        className={cn('w-2 h-2 rounded-full ml-2 shrink-0', t.playing ? 'bg-primary animate-pulse' : loaded ? 'bg-muted-foreground' : 'bg-border')}
        title={t.playing ? 'Playing' : loaded ? 'Loaded' : 'Idle'}
      />
      {exporting && loaded && <ExportClip loaded={loaded} onClose={() => setExporting(false)} />}
    </div>
  )
}

type Format = 'wav' | 'midi'

/** The loaded track's export: WAV (a score's with the passes of its
 *  endless loop chosen) or MIDI, saved under the disc's exports. */
function ExportClip({ loaded, onClose }: { loaded: Loaded; onClose: () => void }) {
  const clip = loaded.clip
  const hasWav = !!(clip.wav || clip.live)
  const [format, setFormat] = useState<Format>(hasWav ? 'wav' : 'midi')
  const [passes, setPasses] = useState(clip.passes ?? 2)
  const [busy, setBusy] = useState(false)

  const run = async () => {
    setBusy(true)
    try {
      const rerender = format === 'wav' && clip.passes && passes !== clip.passes
      const { paths } = await api.export(loaded.sessionId, loaded.resultId, format, undefined, undefined, rerender ? passes : undefined)
      onClose()
      toast({
        tone: 'ok',
        title: `Exported ${basename(paths[0])}`,
        body: paths[0],
        action: { label: 'Show in folder', run: () => void api.reveal(paths[0]) },
      })
    } catch (e) {
      setBusy(false)
      toast({ tone: 'error', title: 'Export failed', body: e instanceof Error ? e.message : String(e) })
    }
  }

  const option = (value: Format, label: string, note: string, enabled: boolean) => (
    <label
      className={cn(
        'flex items-start gap-2.5 rounded-md border px-3 py-2 cursor-pointer',
        format === value ? 'border-primary bg-primary/5' : 'border-border',
        !enabled && 'opacity-50 cursor-not-allowed',
      )}
    >
      <input type="radio" name="format" className="mt-0.5 accent-primary" checked={format === value} disabled={!enabled} onChange={() => setFormat(value)} />
      <span className="space-y-0.5">
        <span className="block text-xs font-medium">{label}</span>
        <span className="block text-[11px] text-muted-foreground leading-snug">{note}</span>
      </span>
    </label>
  )

  return (
    <Dialog title={`Export ${loaded.title}`} onClose={onClose} className="w-[440px]">
      <div className="space-y-2">
        {option('wav', 'WAV audio', hasWav ? 'The track as it plays, rendered to a file.' : 'This track has no audio to render.', hasWav)}
        {format === 'wav' && clip.passes ? (
          <label className="flex items-center gap-2 pl-8 text-[11px] text-muted-foreground" title="Times the endless loop plays before the ending">
            Loop passes
            <input
              type="number"
              min={1}
              max={20}
              value={passes}
              onChange={(e) => setPasses(Math.max(1, Math.min(20, Math.round(Number(e.target.value)) || 1)))}
              className="w-12 h-6 rounded border border-border bg-background px-1 font-mono text-[11px] text-foreground"
            />
            <span>then the ending</span>
          </label>
        ) : null}
        {option('midi', 'MIDI', clip.midi ? 'A standard MIDI file of the score: notes and tempo, no sound.' : 'Only scores have a MIDI version.', !!clip.midi)}
      </div>
      <p className="mt-3 text-[11px] text-muted-foreground">
        Saved as <span className="font-mono">{clip.name}</span> in the disc's exports folder.
      </p>
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={onClose}>
          Cancel
        </Button>
        <Button size="sm" disabled={busy} onClick={() => void run()}>
          {busy ? 'Exporting…' : 'Export'}
        </Button>
      </div>
    </Dialog>
  )
}
