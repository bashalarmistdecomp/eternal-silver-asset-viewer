import type { SceneActor, SceneSheet } from '../api'

// The field's draw rules, as backend formats/field_picture.py `compose`
// draws them: sprite_draw (0x8001A528)'s ordering-table entries, the
// twins behind every body, and the roofs' second copies at the entry
// bg_cover_box_set (0x80013EF0) leaves in each cell.

/** sprite_draw's entry for a body at ground y 0, the key unheld. */
const BODY_ENTRY_TOP = 0x2df
/** Sprite list entries 0x46..0x6D (the twins): behind every body. */
const TWIN_ENTRY = 1 << 20
/** Draw word class 0x2000: its pieces lower the cover cells. */
const CLASS_UNDER = 0x2000

/** The track point in force at tick t: the last at or before it. */
export function pointAt(track: number[][], t: number): number[] {
  let lo = 0
  let hi = track.length - 1
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1
    if (track[mid][0] <= t) lo = mid
    else hi = mid - 1
  }
  return track[lo]
}

/** One actor as it stands at a tick. */
export interface Shown {
  i: number
  x: number
  y: number
  pose: number
  klass: number
  entry: number
  queue: number
}

/** Every actor that draws something at tick t, the hidden groups left out,
 *  and, with the story bits set, those a bit leaves out (MapObjectsInit)
 *  and chests a bit shows open (MapObjectInit). */
export function shownAt(actors: SceneActor[], t: number, hidden: Set<string>, story?: Set<number>): Shown[] {
  const out: Shown[] = []
  actors.forEach((a, i) => {
    if (!a.track || (a.group && hidden.has(a.group))) return
    if (story && a.out != null && story.has(a.out)) return
    const [, x, y, drawn, klass] = pointAt(a.track, t)
    const pose = story && a.open && story.has(a.open[0]) ? a.open[1] : drawn
    if (pose < 0) return
    const depth = a.depth ?? y
    out.push({ i, x, y, pose, klass, entry: a.twin ? TWIN_ENTRY : BODY_ENTRY_TOP - depth, queue: a.queue ?? 0 })
  })
  return out
}

/** A thing to draw: an actor, or a roof cell's second copy. */
export interface Item {
  entry: number
  queue: number
  shown?: Shown
  cell?: [number, number]
}

/** Back to front: entries high to low, and at one entry the later queued
 *  first, so the earlier lies on top. A roof copy takes, in a cell, the
 *  entry less one of the frontmost class-0x2000 sprite whose piece reaches
 *  it (both ends of the piece counted) and is queued after every sprite. */
export function drawItems(shown: Shown[], actors: SceneActor[], sheets: SceneSheet[], isRoof: (cell: number) => boolean, columns: number): Item[] {
  const items: Item[] = shown.map((s) => ({ entry: s.entry, queue: s.queue, shown: s }))
  const cover = new Map<number, number>()
  for (const s of shown) {
    if (s.klass !== CLASS_UNDER) continue
    const pieces = sheets[actors[s.i].sheet].pieces?.[s.pose] ?? []
    const depth = s.entry - 1
    for (const [dx, dy, w, h] of pieces) {
      const x = s.x + dx
      const y = s.y + dy
      for (let cy = y >> 4; cy <= (y + h) >> 4; cy++) {
        if (cy < 0 || cy >= columns) continue
        for (let cx = x >> 4; cx <= (x + w) >> 4; cx++) {
          if (cx < 0 || cx >= columns) continue
          const k = cy * columns + cx
          if (depth < (cover.get(k) ?? Infinity)) cover.set(k, depth)
        }
      }
    }
  }
  const last = Math.max(0, ...shown.map((s) => s.queue)) + 1
  for (const [k, depth] of cover) {
    if (isRoof(k)) items.push({ entry: depth, queue: last, cell: [k % columns, Math.floor(k / columns)] })
  }
  return items.sort((a, b) => b.entry - a.entry || b.queue - a.queue)
}
