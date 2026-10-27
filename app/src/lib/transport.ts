// The audio transport: one clip at a time, played by the webview itself.
//
// Most clips play from an <audio> element fed straight from the backend's
// blob URL, so position, seeking and pausing are the media element's own.
//
// A score plays LIVE, as the game plays it: the backend runs libsnd's
// reader and the SPU a few seconds ahead of what is heard and hands the
// PCM over a chunk at a time (viewer_server.music). Each chunk is an
// AudioBuffer scheduled on the transport's own AudioContext to start where
// the one before it ends, so the music is gapless, and an endless loop
// jumps back for ever, voices ringing on through the jump, for as long as
// the loop switch is on. Off, the score goes on to its ending at the next
// loop end that is not yet heard: what is held ahead from there is fetched
// again. Pausing suspends the context, so what is held waits. A seek asks
// the backend to replay the score up to the place without output.
//
// Positions are shown on the score's MAP: its endless loop played the
// clip's `passes` times, then its ending. Every pass after the map's last
// is shown in that last pass; each chunk carries the marks that say where
// it lies on the map and which part (intro, loop pass n, ending) it is.
//
// The transport is GLOBAL: what it holds plays on across tabs and
// selections until another track takes its place. A track takes it when
// it is selected in a tab of tracks, or asked for by a view (a map's
// music); while a different one is playing, the person is asked first
// (`take`). Closing the game unloads it.

import { useSyncExternalStore } from 'react'
import { ApiError, blobUrl } from './backend'
import { api, type Clip, type MusicChunk, type MusicMark } from './api'
import { confirm } from './confirm'

export interface Loaded {
  clip: Clip
  /** The selection it came from, so views can tell "is this what is playing". */
  resultId: string
  sessionId: string
  /** Where it came from, for the title: tab · entry. */
  source: string
  /** The entry's name, for the question asked before it is swapped. */
  title: string
  /** The program of the disc it came from: a map's music button knows its song by it. */
  program?: string
}

export interface TransportState {
  loaded: Loaded | null
  playing: boolean
  duration: number
  /** Repeat a clip's endless loop, as the game does. */
  looping: boolean
  error: string | null
}

let state: TransportState = { loaded: null, playing: false, duration: 0, looping: true, error: null }
const listeners = new Set<() => void>()

function set(patch: Partial<TransportState>) {
  state = { ...state, ...patch }
  listeners.forEach((l) => l())
}

/** One way of playing the loaded clip. */
interface Engine {
  play(): Promise<void>
  pause(): void
  seek(seconds: number): void
  position(): number
  /** Which part of the score is playing ("intro", "loop 3", "ending"). */
  part?(): string
  looping(on: boolean): void
  release(): void
}

// -- the media element --------------------------------------------------------

let audio: HTMLAudioElement | null = null

function element(): HTMLAudioElement {
  if (audio) return audio
  audio = new Audio()
  audio.preload = 'auto'
  audio.addEventListener('play', () => set({ playing: true, error: null }))
  audio.addEventListener('pause', () => set({ playing: false }))
  audio.addEventListener('ended', () => set({ playing: false }))
  audio.addEventListener('loadedmetadata', () => {
    if (audio && Number.isFinite(audio.duration)) set({ duration: audio.duration })
  })
  audio.addEventListener('error', () => {
    if (audio?.getAttribute('src')) set({ playing: false, error: 'This clip could not be played (it may have expired — select it again).' })
  })
  return audio
}

function mediaEngine(url: string): Engine {
  const a = element()
  a.src = url
  return {
    play: () => a.play(),
    pause: () => a.pause(),
    seek: (seconds) => {
      a.currentTime = seconds
    },
    position: () => a.currentTime,
    looping: () => {},
    release: () => {
      a.pause()
      a.removeAttribute('src')
      a.load()
    },
  }
}

// -- a score played live ------------------------------------------------------

/** Seconds of music held ahead of what is heard. */
const LEAD = 3
/** Seconds asked for at a time; the first after a seek is shorter, so
 *  the music starts sooner. */
const CHUNK = 1
const FIRST = 0.25
/** Seconds from now a first chunk starts (and one that came too late). */
const START = 0.05
/** A chunk starting sooner than this plays as it is when the loop switch
 *  changes; the switch holds from the next one. */
const SWITCH_MARGIN = 0.25

let context: AudioContext | null = null
let contextRate = 0

/** The transport's own AudioContext, at the music's rate when the webview
 *  allows it: chunk boundaries then fall on the context's own frames. */
function audioContext(rate: number): AudioContext {
  if (context && contextRate !== rate) {
    void context.close()
    context = null
  }
  if (!context) {
    try {
      context = new AudioContext({ sampleRate: rate })
    } catch {
      context = new AudioContext()
    }
    contextRate = rate
  }
  return context
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

interface Piece {
  node: AudioBufferSourceNode
  /** Stream frames it holds. */
  from: number
  to: number
}

function liveEngine(loaded: Loaded): Engine {
  const { sessionId: sid, resultId: rid } = loaded
  const music = loaded.clip.live!
  const rate = music.rate
  const ctx = audioContext(rate)
  const plain: MusicMark[] = [[0, 0, music.frames, '', 0]]

  let gen = 0 // bumped whenever what is held is dropped: stale replies are ignored
  let released = false
  let playing = false
  let positioned = false // the backend's stream stands where `fetchAt` says
  let resumeAt: number | null = 0 // map seconds a play() starts from, when not positioned
  let marks: MusicMark[] = plain
  let fetchAt = 0 // next stream frame to fetch
  let end: number | null = null // stream frame where the music ends, once known
  /** Stream frame `frame` is heard at context frame `at`. */
  let anchor: { frame: number; at: number } | null = null
  let held: Piece[] = []
  let still = 0 // the stream frame shown while nothing is anchored
  let seeking = false
  let nextSeek: number | null = null

  const startOf = (p: Piece) => (anchor ? (anchor.at + (p.from - anchor.frame)) / rate : Infinity)

  const streamPos = (): number => {
    if (!anchor) return still
    const f = anchor.frame + (ctx.currentTime * rate - anchor.at)
    return Math.max(anchor.frame, Math.min(f, fetchAt))
  }

  const markAt = (f: number): MusicMark => {
    let m = marks[0]
    for (const x of marks) {
      if (x[0] > f) break
      m = x
    }
    return m
  }

  const addMarks = (more: MusicMark[]) => {
    const byFrame = new Map(marks.map((m) => [m[0], m] as const))
    for (const m of more) byFrame.set(m[0], m)
    marks = [...byFrame.values()].sort((a, b) => a[0] - b[0])
  }

  const dropFrom = (frame: number) => {
    for (const p of held) {
      if (p.from < frame) continue
      p.node.onended = null
      try {
        p.node.stop()
      } catch {
        // not started
      }
      p.node.disconnect()
    }
    held = held.filter((p) => p.from < frame)
  }

  /** Drop everything held; stand at map `seconds` until played. */
  const reset = (seconds: number) => {
    gen++
    dropFrom(-Infinity)
    anchor = null
    end = null
    positioned = false
    resumeAt = seconds
    marks = plain
    still = Math.round(seconds * rate)
  }

  const finished = () => {
    // stands at the end; play() starts it again from the top
    const at = end ?? fetchAt
    const m = markAt(at)
    reset(0)
    still = at
    marks = [m]
    playing = false
    set({ playing: false })
  }

  const schedule = (c: MusicChunk) => {
    const n = c.frames
    const buf = ctx.createBuffer(2, n, rate)
    const left = buf.getChannelData(0)
    const right = buf.getChannelData(1)
    for (let i = 0; i < n; i++) {
      left[i] = c.pcm[2 * i] / 32768
      right[i] = c.pcm[2 * i + 1] / 32768
    }
    const now = Math.ceil(ctx.currentTime * rate)
    if (!anchor || anchor.at + (c.from - anchor.frame) < now) {
      // the first chunk, or one that came too late to follow on
      anchor = { frame: c.from, at: now + Math.round(START * rate) }
    }
    const node = ctx.createBufferSource()
    node.buffer = buf
    node.connect(ctx.destination)
    const piece: Piece = { node, from: c.from, to: c.from + n }
    node.onended = () => {
      held = held.filter((p) => p !== piece)
      if (!released && end !== null && piece.to >= end) finished()
    }
    node.start((anchor.at + (c.from - anchor.frame)) / rate)
    held.push(piece)
  }

  const pump = async (my: number) => {
    while (my === gen && !released && end === null) {
      const ahead = anchor ? (anchor.at + (fetchAt - anchor.frame)) / rate - ctx.currentTime : 0
      if (ahead > LEAD) {
        await sleep(Math.min(500, (ahead - LEAD) * 1000 + 20))
        continue
      }
      let chunk: MusicChunk
      try {
        chunk = await api.musicPcm(sid, rid, fetchAt, Math.round((anchor ? CHUNK : FIRST) * rate))
      } catch (e) {
        if (my !== gen || released) return
        if (e instanceof ApiError && e.status === 409) {
          // the stream is not where this thought: stand it here again
          void restart(position())
          return
        }
        if (e instanceof ApiError && e.status === 404) {
          // closed by a newer selection: play() opens it again
          reset(position())
          playing = false
          set({ playing: false })
          return
        }
        // it stops where it failed: play() stands the stream there again
        reset(position())
        playing = false
        set({ playing: false, error: `Playback failed: ${e instanceof Error ? e.message : String(e)}` })
        return
      }
      if (my !== gen || released) return
      addMarks(chunk.marks)
      if (chunk.frames > 0) schedule(chunk)
      fetchAt = chunk.from + chunk.frames
      if (chunk.done) {
        end = fetchAt
        if (!held.length) finished()
      }
    }
  }

  /** Stand the stream at map `seconds` and play on from there. Seeks made
   *  while one is on its way are folded into the last of them. */
  const restart = async (seconds: number) => {
    reset(seconds)
    resumeAt = null
    if (seeking) {
      nextSeek = seconds
      return
    }
    seeking = true
    try {
      let target = seconds
      for (;;) {
        const loop = state.looping
        const r = await api.musicSeek(sid, rid, target, loop)
        if (released) return
        if (nextSeek !== null) {
          target = nextSeek
          nextSeek = null
          continue
        }
        if (resumeAt !== null) return // stopped meanwhile
        marks = plain
        addMarks(r.marks)
        fetchAt = r.from
        still = r.from
        positioned = true
        void pump(gen)
        if (state.looping !== loop) void switchLoop(state.looping)
        return
      }
    } catch (e) {
      nextSeek = null
      if (!released) {
        // it stands where it was to go: play() asks again
        resumeAt = position()
        playing = false
        set({ playing: false, error: `This music could not be played: ${e instanceof Error ? e.message : String(e)}` })
      }
    } finally {
      seeking = false
    }
  }

  const switchLoop = async (on: boolean) => {
    if (!positioned || released) return
    const soon = ctx.currentTime + SWITCH_MARGIN
    const later = held.filter((p) => startOf(p) > soon).map((p) => p.from)
    const at = later.length ? Math.min(...later) : fetchAt
    const my = gen
    let r: { from: number | null; marks?: MusicMark[] }
    try {
      r = await api.musicLoop(sid, rid, on, at)
    } catch {
      return // a closed stream: the next play() seeks with the switch as it is
    }
    if (my !== gen || released || r.from === null) return
    const g = ++gen
    dropFrom(r.from)
    marks = marks.filter((m) => m[0] < r.from!)
    addMarks(r.marks ?? [])
    fetchAt = r.from
    end = null
    void pump(g)
  }

  const position = (): number => {
    const f = streamPos()
    const m = markAt(f)
    return Math.min(m[1] + (f - m[0]), m[2]) / rate
  }

  return {
    async play() {
      if (released || playing) return
      playing = true
      set({ playing: true, error: null })
      if (!positioned && resumeAt !== null) void restart(resumeAt)
      if (ctx.state === 'suspended') await ctx.resume()
    },
    pause() {
      if (!playing) return
      playing = false
      void ctx.suspend()
      set({ playing: false })
    },
    seek(seconds) {
      if (playing) void restart(seconds)
      else reset(seconds)
    },
    position,
    part() {
      const m = markAt(streamPos())
      return m[3] === 'loop' ? `loop ${m[4]}` : m[3]
    },
    looping(on) {
      void switchLoop(on)
    },
    release() {
      released = true
      reset(0)
    },
  }
}

// -- the transport ------------------------------------------------------------

let engine: Engine | null = null

export const transport = {
  get state() {
    return state
  },
  subscribe(fn: () => void) {
    listeners.add(fn)
    return () => {
      listeners.delete(fn)
    }
  },

  /** Load a clip, replacing whatever was loaded. */
  load(loaded: Loaded | null) {
    if (loaded && state.loaded?.resultId === loaded.resultId) return
    engine?.release()
    engine = null
    const clip = loaded?.clip
    if (clip?.live && loaded) engine = liveEngine(loaded)
    else if (clip?.wav) engine = mediaEngine(blobUrl(clip.wav, 'wav'))
    set({ loaded, playing: false, duration: clip?.seconds ?? 0, error: null })
  },

  /** Whether `next` may stop what plays: asked only while a track plays. */
  async ask(next: string): Promise<boolean> {
    const cur = state.loaded
    if (!cur || !state.playing) return true
    return confirm({
      title: 'Stop the music?',
      body: `“${cur.title}” is currently playing. Loading “${next}” will stop playback.`,
      ok: 'Continue',
      cancel: 'Cancel',
    })
  },

  /** Load `next` in place of what is loaded, asking first while another
   *  track plays. True when `next` is loaded (or already was). */
  async take(next: Loaded): Promise<boolean> {
    if (state.loaded?.resultId === next.resultId) return true
    if (!(await this.ask(next.title))) return false
    this.load(next)
    return true
  },

  /** The result the backend must keep playing and held: the loaded one. */
  keep(): string | undefined {
    return state.loaded?.resultId
  },

  /** Repeat a clip's endless loop, or play on into the score's ending. */
  setLooping(looping: boolean) {
    set({ looping })
    engine?.looping(looping)
  },

  canPlay(): boolean {
    const clip = state.loaded?.clip
    return !!(clip?.wav || clip?.live)
  },

  async play() {
    if (!engine) return
    try {
      await engine.play()
    } catch (e) {
      set({ error: `Playback failed: ${e instanceof Error ? e.message : String(e)}` })
    }
  },

  pause() {
    engine?.pause()
  },

  toggle() {
    if (state.playing) this.pause()
    else void this.play()
  },

  stop() {
    if (!engine) return
    engine.pause()
    engine.seek(0)
    set({ playing: false })
  },

  seek(seconds: number) {
    if (!engine) return
    engine.seek(Math.max(0, Math.min(seconds, state.duration || seconds)))
    listeners.forEach((l) => l())
  },

  /** Seconds into the clip (on a score's map) — read per animation frame by playheads. */
  position(): number {
    return engine?.position() ?? 0
  },

  /** Which part of a score is playing: "intro", "loop 3", "ending", or "". */
  part(): string {
    return engine?.part?.() ?? ''
  },

  clearError() {
    set({ error: null })
  },
}

export function useTransport(): TransportState {
  return useSyncExternalStore(transport.subscribe, () => state)
}
