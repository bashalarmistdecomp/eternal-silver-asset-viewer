// Typed wrappers over the backend routes in backend/viewer_server/routes.py.

import type { Tone } from '../components/ui/badge'
import type { AnimDef } from './game/actorAnim'
import { postBytes, request, requestBytes } from './backend'

/** The library folder the backend serves: discs and everything extracted. */
export interface LibraryFolder {
  path: string
  /** <library>/discs, where disc images may be kept — null until it exists. */
  discs: string | null
  /** False until the first disc is extracted into it. */
  exists: boolean
}

export interface DiscRow {
  /** Its path under the library, e.g. SLUS_006.28/raw/SLUS_008.99. */
  key: string
  discId: string
  label: string
  heading: string
  region: string
  volumeId: string
  role: string
  files: number
  bytes: number
  readable: boolean
  /** The disc image it was extracted from, if it can still be found. */
  source: string | null
  identifiedBy: 'checksum' | 'serial' | 'unrecognized'
  warning: { text: string; tone: 'warn' | 'danger' } | null
  hasLunadata: boolean
}

/** A disc as the library lists it. */
export interface LibraryDisc extends DiscRow {
  /** Its index in the library (backend viewer_server/index.py): what its
   *  tabs list and its links, kept so the game opens without reading the
   *  disc whole. Until it is ready the disc is read from its files. */
  index: DiscIndex
}

export interface DiscIndex {
  state: 'ready' | 'making' | 'queued' | 'missing' | 'stale' | 'off'
  /** While it is made: what is being read, and how far. */
  message?: string
  current?: number
  total?: number
  /** Once ready: its size on disk. */
  bytes?: number
}

/** A disc whose index is being made, or waits its turn. */
export function indexing(library: Library): boolean {
  return [...library.games, ...library.others].some((g) =>
    g.discs.some((d) => d.disc && (d.disc.index.state === 'making' || d.disc.index.state === 'queued')),
  )
}

export interface PoolRow {
  /** "" until the image is extracted: it is identified then. */
  serial: string
  title: string
  label: string
  path: string
  sha256: string
  bytes: number
}

/** One disc of a game's slot: extracted, waiting in discs/, or not added yet. */
export interface SlotDisc {
  serial: string
  /** Its short tag where items are listed: "US 1", "JP 1", "Making-of". */
  tag: string
  label: string
  state: 'present' | 'in-folder' | 'missing'
  disc: LibraryDisc | null
  pool: PoolRow | null
}

/** A game the library opens whole: every disc of every version of it. */
export interface Slot {
  /** "lunar-1", or "program:<serial>" for a disc of no game. */
  key: string
  title: string
  programs: string[]
  discs: SlotDisc[]
  /** How many of its discs are extracted. */
  present: number
  /** A game not read in full yet: it opens with only the tabs any
   *  PlayStation disc has (lib/tabs PARTIAL). Never a disc of no game. */
  partial: boolean
}

export interface Library {
  folder: LibraryFolder
  games: Slot[]
  /** Discs that belong to no game, one slot per program. */
  others: Slot[]
  /** Images in discs/ that nothing names yet: identified when extracted. */
  unsorted: PoolRow[]
}

/** Every image in discs/ that could be extracted. */
export function poolRows(library: Library): PoolRow[] {
  const inSlots = [...library.games, ...library.others].flatMap((g) => g.discs.flatMap((d) => (d.pool ? [d.pool] : [])))
  return [...inSlots, ...library.unsorted]
}

export interface Job {
  id: string
  kind: string
  state: 'running' | 'done' | 'error'
  /** "" while it does its first part; "index": an extraction, done
   *  extracting, indexes the discs (the library screen shows it). */
  stage: string
  message: string
  current: number
  total: number
  result: unknown
  error: string
  seconds: number
}

/**
 * One disc image of an extraction job (backend viewer_server/library.py,
 * "the batch"): found in a folder, or a dump to make again. The job
 * extracts the waiting ones in turn and says what became of each.
 */
export interface BatchDisc {
  /** The image (its cue sheet where it has one), and its file name. */
  path: string
  file: string
  /** The program its SYSTEM.CNF boots; "" where none was read. */
  serial: string
  /** "US 2"; "" for a disc the viewer does not know. */
  tag: string
  label: string
  /** The library slot it joins, and its title. */
  game: string | null
  gameTitle: string
  state: 'waiting' | 'extracting' | 'added' | 'failed' | 'skipped'
  /** Why it was skipped or failed, in words. */
  why: string
  /** The dump it replaces; once added, the one it became. */
  key: string | null
  files?: number
  /** False: gamedb placed it by its SYSTEM.CNF only, not its checksum. */
  recognized?: boolean
}

/** An extraction job's discs, as far as it has gone. */
export function batchOf(job: Job): BatchDisc[] {
  return (job.result as { discs?: BatchDisc[] } | null)?.discs ?? []
}

/** The job has done what the app waits for: it ended, or it only indexes now. */
export function extracted(job: Job): boolean {
  return job.state !== 'running' || job.stage === 'index'
}

export interface TabMeta {
  index: number
  key: string
  name: string
  views: string[]
  view: string | null
  /** The view Advanced mode opens the tab on, if it has one. */
  technicalView: string | null
  viewsChangeItems: boolean
  supportsZoom: boolean
  supportsGrid: boolean
  supportsLayers: boolean
  /** The provider's own docstring: what the tab shows and how it knows. */
  about: string
  /** What the tab holds, in a fan's words (Fan mode's start page); empty
   *  where the tab has not said, and `about` is shown. */
  fanAbout: string
  /** The discs of the open game that have this tab, by tag. */
  discs: string[]
}

/** One open game: every extracted disc of it. */
export interface Session {
  id: string
  /** The library slot it was opened from. */
  key: string
  title: string
  label: string
  status: string
  members: { tag: string; disc: DiscRow }[]
  /** The first disc's program, where exports land. */
  program: string
  plugin: boolean
  /** As its library slot's `partial`. */
  partial: boolean
  exportsDir: string
  tabs: TabMeta[]
}

export interface Row {
  title: string
  sub: string
  /** The provider's label as written; the filter matches against it. */
  label: string
  /** A placeholder ("No sprite pages found"), not an item. */
  empty: boolean
  indent?: number
  badge?: string
  tone?: 'ok' | 'warn' | 'info' | 'muted'
  mono?: boolean
  /** The title runs onto a second line instead of being cut short. */
  wrap?: boolean
  progress?: number
  /** Selecting it does something (builds an index) rather than shows something. */
  action?: boolean
  /** The heading it is listed under; rows of a group come together. */
  group?: string
  /** What the heading means, on hover. */
  groupNote?: string
  /** The discs that hold it, by tag. */
  tags: string[]
  /** When its discs hold different contents: each version's discs. */
  versions?: string[][]
  /** How Fan mode words it, where that differs: a plain title, a second
   *  line in a fan's words (no file names, no hex). */
  fan?: { title?: string; sub?: string }
}

export interface Items {
  tab: number
  view: string | null
  layerOptions: number
  rows: Row[]
}

export interface Layer {
  label: string
  blob: string
  w: number
  h: number
}

export interface Waveform {
  lo: number[]
  hi: number[]
  seconds: number
  /** Loop start as a fraction of the shown length. */
  loop: number | null
  /** Loop end, when the loop does not run to the end. */
  loopEnd?: number | null
  note?: string
  /** Columns of the whole, when they come in as the server plays it
   *  (`pending` until all have). */
  columns?: number
  pending?: boolean
}

export interface Lane {
  channel: number
  label: string
  /** [tick, duration, note, velocity] */
  notes: [number, number, number, number][]
}

export interface ArrangementData {
  resolution: number
  ticks: number
  seconds: number
  beatsPerBar: number
  /** [seconds, tick] breakpoints; tempo is constant between them. */
  tempo: [number, number][]
  lanes: Lane[]
}

export interface VideoInfo {
  id: string
  duration: number
  sectors: number
  sectorsPerSecond: number
  fromImage: boolean
  note: string
  /** A pixel's width over its height as the game shows the movie, or null
   *  when the program's player is not known (shown square). */
  pixelAspect: [number, number] | null
  shapeNote: string
}

export interface Clip {
  name: string
  wav: string | null
  midi: string | null
  seconds: number | null
  /** [start, end] seconds of a loop the game repeats for ever. */
  loop?: [number, number] | null
  /** Passes of that loop in the WAV, when an export can choose others. */
  passes?: number | null
  /** Set when the score plays live: the server plays it a chunk at a time.
   *  `seconds`, `loop` and `passes` then lay out its MAP. */
  live?: LiveMusic | null
  /** The songs the game plays it for. */
  songs?: number[] | null
  /** What it is, by the game's words first: the songs' titles, "sound
   *  effect 9", a bank's samples; a voice by who says what. */
  title?: string | null
  /** The kind of thing it is, when it is one: "song", "sound-effect". */
  kind?: string | null
}

/** A thing of the game: its kind and its number (backend viewer_tabs/refs.py). */
export interface Ref {
  kind: string
  id: number[]
}

/** A link to a thing, as a card or a result lists it. */
export interface LinkItem {
  ref: Ref
  title: string
  /** "map 21" */
  written: string
  /** "map 0x15" */
  hex: string
  /** How it is linked, in plain words. */
  note: string
  /** The function that makes the link. */
  proof?: string
  /** Its kind's home is only in Advanced mode (a resource, a sound bank):
   *  Fan mode shows it with the extended info. */
  advanced?: boolean
}

/** A card's or a result's links: what it points at ('out'), what points at it ('in'). */
export interface LinkGroup {
  title: string
  dir: 'out' | 'in'
  links: LinkItem[]
}

/** The row that is a thing's home (GET locate). */
export interface Place {
  tab: number
  key: string
  name: string
  view: string | null
  item: number
  version: number
}

/** What a thing shows when a link is followed (backend viewer_tabs/links). */
export interface Card {
  ref: Ref
  kind: string
  kindName: string
  written: string
  hex: string
  title: string
  subtitle: string
  facts: [string, string][]
  note: string
  groups: LinkGroup[]
  /** The extended info: the code's name, the hex, where it is stored. */
  extended: [string, string][]
  /** The functions that prove what it says. */
  proven: string[]
  error: string
  picture?: { blob: string; w: number; h: number }
  /** Its "Open in": the first of its homes. */
  home: Place | null
  /** Every tab's row that is its home, in the tabs' order (a chest's: its
   *  map, and Items' Treasure). */
  homes?: Place[]
  /** The disc it was read from, by tag. */
  disc: string
}

/** A score playing live. Its MAP: the endless loop played `passes` times,
 *  then the ending, `frames` long; later passes are shown in the last. */
export interface LiveMusic {
  rate: number
  channels: number
  frames: number
  passes: number
  /** Map frame where the endless loop's first pass begins. */
  firstPass: number | null
  /** Map frames of its last pass. */
  loop: [number, number] | null
}

/** [stream frame, map frame, map limit, part, pass]: from that stream
 *  frame on, the map position counts up from `map frame`, never past its
 *  limit. Part is "intro", "loop", "ending" or "" (no endless loop). */
export type MusicMark = [number, number, number, string, number]

export interface MusicChunk {
  pcm: Int16Array
  from: number
  frames: number
  done: boolean
  marks: MusicMark[]
}

export interface MusicOverview {
  columns: number
  from: number
  lo: number[]
  hi: number[]
  done: boolean
  text?: string
  info?: string
  error?: string
}

export interface SceneSheet {
  blob: string
  w: number
  h: number
  cellW: number
  cellH: number
  /** Where the actor anchor sits in every cell. */
  anchorX: number
  anchorY: number
  columns: number
  poses: number
  label: string
  anims: AnimDef[]
  /** A field sheet's pieces per pose, [dx, dy, w, h] about the anchor (bg_cover_box_set). */
  pieces?: number[][][]
  /** A field sheet: whether each pose draws anything. */
  drawn?: boolean[]
}

export interface SceneActor {
  sheet: number
  /** The anchor, in scene pixels. */
  x: number
  y: number
  /** actor +0x0C bit 13: drawn mirrored about the anchor column. */
  mirror: boolean
  anim: number
  label: string
  /** A field actor (backend/viewer_tabs/field_view.py): what it is, its
   *  group (a layer), its sprite list place and how it is drawn. */
  note?: string
  group?: string
  twin?: boolean
  queue?: number
  semi?: boolean
  /** The ground y when it is not the drawn y (the party's body). */
  depth?: number | null
  /** [tick, x, y, pose, class] at tick 0 and wherever one changes; pose -1 draws nothing. */
  track?: number[][]
  /** A field actor: the story bit that leaves it out while set. */
  out?: number | null
  /** A chest: [the story bit that shows it open, the pose it shows then]. */
  open?: [number, number]
}

/** What the client draws a map's ground from (backend
 *  viewer_tabs/field_view.py `ground_data`; lib/game/ground.ts). */
export interface FieldGround {
  /** The bytes: the tile words, the pages and the tile animations' images. */
  blob: string
  /** name -> [offset, length] in the blob. */
  parts: Record<string, [number, number]>
  pages: { page: number; w: number; h: number; part: string }[]
  columns: number
  /** CLUT rows 500 / 501 as colour words. */
  rows: number[][]
  /** The cover rows 510 / 511 the roofs' copies are drawn through. */
  cover: number[][]
  /** Bit-15 texels are drawn half and half over the second layer. */
  blend: boolean
  /** The second layer, when it is drawn behind the tiles: its plane as
   *  row-508 colour indexes (16 * CLUT + texel, 0 none), tiled over the
   *  map, and row 508 as the load sets it. */
  layer2: { part: string; w: number; h: number; row: number[] } | null
  tiles: { delay: number; frames: number; count: number; tile: number; source: number }[]
  /** The palette animation, when the map has one that changes row 501. */
  palette: FieldPalette | null
}

/** One slot of a palette animation (backend formats/palette_animation.py). */
export interface PaletteSlot {
  /** 1 copy a strip frame, 2 turn the colours up one, 3 down one. */
  mode: number
  delay: number
  frames: number
  /** The first colour of row 501 it changes, and how many. */
  first: number
  count: number
  /** Mode 1: the strip's frames, `count` words each. */
  strip: number[]
}

export interface FieldPalette {
  set: number
  slots: PaletteSlot[]
  /** Row 508's CLUTs taken again from row 501 every frame: [first, count]. */
  copy: [number, number] | null
}

/** One object the map's object set makes, or the party (Objects panel). */
export interface FieldObject {
  /** The scene actor that draws it, or null when its sheet draws nothing. */
  actor: number | null
  /** By its kind: "entity 3", "chest 5", "the party". */
  name: string
  row: number | null
  def: number | null
  kind: number | null
  group: string
  data: number
  x: number
  y: number
  facing: number
  think: number | null
  how: string
  klass: number
  /** The story flag that keeps it out while set. */
  out: number | null
  /** The story flag that shows a chest open. */
  open: number | null
  /** What it is (entity, map monster, chest, trigger), for its card. */
  ref?: Ref | null
}

/** One texture page the map loads, through each CLUT that draws it. */
export interface FieldTilesetPage {
  page: number
  label: string
  w: number
  h: number
  /** `layer` indexes the result's layers (export writes it). */
  rows: { label: string; uses: number; what: string; layer: number }[]
  notes: string[]
}

/** One row of a map's bg change table (backend formats/bg_change.py):
 *  a rectangle of 8-px cells copied over from each source in turn. */
export interface BgChangeRow {
  id: number
  x: number
  y: number
  w: number
  h: number
  bit: number | null
  /** Field frames between two copies. */
  frames: number
  sound: number
  sources: [number, number][]
  /** 'state': its story bit keeps it; 'door': a kind-3 cell starts it, per
   *  visit; 'other': started by a script, or never. */
  kind: 'state' | 'door' | 'other'
  /** The kind-3 cells that start it, in pixels. */
  triggers: [number, number][]
}

/** A story bit and what it changes on this map. */
export interface StoryBit {
  bit: number
  /** Bg change rows it leaves copied. */
  rows: number[]
  /** Actors it leaves out. */
  hides: number[]
  /** Chests it shows open (actors). */
  opens: number[]
  /** Other maps whose rows use it: [map id, place]. */
  maps: [number, string][]
  /** The flag, for its card. */
  ref?: Ref
}

/** What a field scene adds (backend/viewer_server/present.py `_field`). */
export interface FieldScene {
  ticks: number
  ground: FieldGround
  /** [group, its name on a toggle], the groups the actors fall in. */
  groups: [string, string][]
  objects: FieldObject[]
  story: { rows: BgChangeRow[]; bits: StoryBit[] }
  tileset: FieldTilesetPage[]
  /** What a player can see (backend formats/map_reach.py); null when no
   *  way in reaches the map. */
  reach: FieldReach | null
}

/** The In game view: a mask, black where the camera never shows. */
export interface FieldReach {
  /** A PNG blob, a pixel per `scale` map pixels: opaque black where hidden. */
  mask: string
  scale: number
  /** [left, top, right, bottom] of what it shows, in map pixels. */
  bbox: [number, number, number, number]
  /** Each camera area (a way in's limits), cut to what it shows: the same form. */
  areas: [number, number, number, number][]
}

/** Actors the client animates from pose sheets + anim tables (backend/viewer_tabs/scene.py). */
export interface Scene {
  w: number
  h: number
  background: string | null
  sheets: SceneSheet[]
  actors: SceneActor[]
  /** 'y': lower on screen draws in front (the battle's OT depth); 'order': list order;
   *  'field': the field's draw rules, played from tracks (FieldSceneView). */
  depth: 'y' | 'order' | 'field'
  labels: boolean
  tickHz: number
  tickNote: string
  field?: FieldScene
}

export interface Result {
  id: string
  label: string
  info: string
  layers?: Layer[]
  frames?: { blobs: string[]; w: number; h: number; intervalMs: number }
  scene?: Scene
  arrangement?: ArrangementData
  waveform?: Waveform
  /** A box of facts (a disc file, an STR's details, a sample's tone). */
  summary?: { title: string; fields: [string, string][] }
  table?: {
    columns: string[]
    rows: string[][]
    /** Column groups, left to right (enemy_templates: proven / unread). */
    groups?: { label: string; span: number; tone?: 'ok' | 'muted' }[]
    /** column -> what the exporter's field notes say it is. */
    notes?: Record<string, string>
  }
  text?: string
  /** `text` as Fan mode shows it, where that differs (no offsets). */
  fanText?: string
  textWrap?: boolean
  sheet?: Sheet
  audio?: Clip
  /** The thing shown, and its links. */
  ref?: Ref
  links?: LinkGroup[]
  /** The thing's title, as a link to it shows it (a character's name), and its
   *  reference, in decimal ("character 2") and in hex. */
  title?: string
  written?: string
  hex?: string
  /** Its card laid out as the page (a bromide's, round its show). */
  page?: Omit<Card, 'picture' | 'home' | 'disc'>
  /** A picture the screen looks down, a window of it a frame (a bromide). */
  pan?: Pan
  /** The disc it came from, by tag. */
  disc?: string
  video?: VideoInfo
  /** The discs holding the version shown, its index, and every version's discs. */
  tags: string[]
  version: number
  versions: string[][]
  /** The program of the disc it came from, and where its exports go. */
  program?: string
  exportsDir?: string
}

/** A picture the screen looks down (stage/BromideView): the whole picture,
 *  the screen's size, and each frame's first row and fade, `hz` a second. */
export interface Pan {
  blob: string
  w: number
  h: number
  screenW: number
  screenH: number
  hz: number
  /** The picture's row the screen begins at, each frame. */
  rows: number[]
  /** What the fade takes off each colour, 0 to 255, each frame. */
  dark: number[]
}

/** A page laid out by the app (stage/SheetView): the Disc tab's page. */
export interface Sheet {
  title: string
  /** The title is a name of data (a file name), set in the mono face. */
  titleMono?: boolean
  subtitle?: string
  /** Its picture, shown by the title (an item's menu icon, a monster). */
  picture?: { blob: string; w: number; h: number }
  badges?: { text: string; tone: Tone; hint?: string }[]
  sections: SheetSection[]
}

export interface SheetSection {
  title: string
  /** Shown at the right of the section's heading. */
  aside?: string
  /** What proves the section or where it is stored (a function, a
   *  resource): by the heading in Advanced mode, in the folded extended
   *  info in Fan mode. */
  cite?: string
  /** The note in plain words, for Fan mode ("" for none): `note` then
   *  cites the code, and Fan mode moves it to the extended info. */
  fanNote?: string
  /** facts: keys in words, values as data; glossary: keys as data, values in words; prose: both in words. */
  style?: 'facts' | 'glossary' | 'prose'
  /** [key, value, hint] */
  fields?: [string, string, string?][]
  /** A tab, on or off; `icon` is its provider's key. */
  chips?: { label: string; on: boolean; why?: string; icon?: string }[]
  verdict?: { text: string; tone: Tone }
  /** Bytes to show as a hex dump: `bytes` as hex, the first at `offset`. */
  hex?: { offset: number; bytes: string }
  /** A small table; a right-aligned column holds numbers. */
  table?: { columns: string[]; rows: string[][]; align?: ('left' | 'right')[] }
  /** Names of data (functions, files), one per line. */
  list?: string[]
  /** Pictures side by side, each with a caption; one with a ref opens its card. */
  pictures?: SheetPicture[]
  /** Paragraphs, split by a blank line. */
  note?: string
  /** Links, grouped as a card groups them. */
  links?: LinkGroup[]
  /** Extended info: folded in Fan mode, open in Advanced. */
  extended?: boolean
  /** Where the result's sound (its waveform or arrangement) is laid out,
   *  in place of a card. */
  sound?: boolean
}

export interface SheetPicture {
  blob: string
  w: number
  h: number
  caption?: string
  ref?: Ref
}

export interface VideoChunk {
  start: number
  next: number
  done: boolean
  frames: { t: number; w: number; h: number; png: string }[]
  audio: { rate: number; channels: number; pcm: string } | null
}

export const api = {
  library: () => request<Library>('GET', '/api/library'),
  /** A disc image, or a folder: every disc in it the library does not hold yet. */
  importDiscs: (path: string) => request<Job>('POST', '/api/import', { path }),
  /** A disc's dump made again, from its image or from `path` when the image moved. */
  reextract: (key: string, path?: string) => request<Job>('POST', '/api/reextract', path ? { key, path } : { key }),
  /** Every disc of a game (a library slot) made again from its image. */
  reextractGame: (game: string) => request<Job>('POST', '/api/reextract', { game }),
  job: (id: string) => request<Job>('GET', `/api/jobs/${id}`),
  reveal: (path: string) => request<{ ok: boolean }>('POST', '/api/reveal', { path }),

  open: (key: string) => request<Session>('POST', '/api/sessions', { key }),
  close: (sid: string) => request<{ ok: boolean }>('DELETE', `/api/sessions/${sid}`),

  items: (sid: string, tab: number, view: string | null) =>
    request<Items>('GET', `/api/sessions/${sid}/tabs/${tab}/items`, undefined, { view }),
  select: (sid: string, tab: number, view: string | null, item: number, version = 0, keep?: string) =>
    request<Result>('POST', `/api/sessions/${sid}/tabs/${tab}/select`, { view, item, version, keep }),
  export: (sid: string, result: string, kind: 'png' | 'wav' | 'midi', layer?: number, all?: boolean, passes?: number) =>
    request<{ paths: string[] }>('POST', `/api/sessions/${sid}/export`, { result, kind, layer, all, passes }),
  videoChunk: (sid: string, vid: string, start: number, count: number) =>
    request<VideoChunk>('GET', `/api/sessions/${sid}/videos/${vid}/chunk`, undefined, { start, count }),

  async musicPcm(sid: string, rid: string, from: number, frames: number): Promise<MusicChunk> {
    const { data, headers } = await requestBytes(`/api/sessions/${sid}/music/${rid}/pcm`, { from, frames })
    const where = JSON.parse(headers.get('X-Music') ?? '{}') as Omit<MusicChunk, 'pcm'>
    return { ...where, pcm: new Int16Array(data) }
  },
  /** Save a picture the app drew of result `rid`, `scale` times as big, under the item's exports folder. */
  save: (sid: string, rid: string, name: string, png: Blob, scale = 1) =>
    postBytes<{ path: string }>(`/api/sessions/${sid}/save`, png, { result: rid, name, scale }),
  /** The row that is a thing's home, on disc `disc`. */
  locate: (sid: string, ref: Ref, disc?: string) =>
    request<Place>('GET', `/api/sessions/${sid}/locate`, undefined, { kind: ref.kind, id: ref.id.join('/'), disc }),
  /** A thing's card, as disc `disc` knows it. */
  card: (sid: string, ref: Ref, disc?: string) =>
    request<Card>('GET', `/api/sessions/${sid}/card`, undefined, { kind: ref.kind, id: ref.id.join('/'), disc }),
  /** Move to `seconds` on the map; a closed stream of a held selection opens again. */
  musicSeek: (sid: string, rid: string, seconds: number, loop: boolean, keep?: string) =>
    request<{ from: number; marks: MusicMark[] }>('POST', `/api/sessions/${sid}/music/${rid}/seek`, { seconds, loop, keep }),
  /** The loop switch from stream frame `at` on: `from` set when what the app holds from there must be fetched again. */
  musicLoop: (sid: string, rid: string, loop: boolean, at: number) =>
    request<{ from: number | null; marks?: MusicMark[] }>('POST', `/api/sessions/${sid}/music/${rid}/loop`, { loop, at }),
  musicOverview: (sid: string, rid: string, have: number, wait: number) =>
    request<MusicOverview>('GET', `/api/sessions/${sid}/music/${rid}/overview`, undefined, { have, wait }),
}

/** Poll a job until it ends, or reaches `stage`; `onProgress` sees every state on the way. */
export async function waitFor(job: Job, onProgress?: (j: Job) => void, everyMs = 250, stage?: string): Promise<Job> {
  let j = job
  onProgress?.(j)
  while (j.state === 'running' && !(stage && j.stage === stage)) {
    await new Promise((r) => setTimeout(r, everyMs))
    j = await api.job(j.id)
    onProgress?.(j)
  }
  return j
}
