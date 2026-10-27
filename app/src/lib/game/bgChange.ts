// A map's bg changes as the game plays them (backend formats/bg_change.py):
// bg_both_copy (0x800153A0) copies a rectangle of tile words from a source
// place, every value halved for the 16-px tile plane (bg_copy (0x80015224)).
// MapBgChangeStoryBitsCopy (0x80059B6C) copies the last source of every row
// whose story bit is set, rows 0 to 0x7F in order, so where two rows write
// the same cells the later row wins.

import type { BgChangeRow } from '../api'

const TILES = 128

/** One copy of a row's source `k`, over `w` in place, cell by cell in row
 *  order as bg_copy reads the live plane; a cell off the plane reads 0. */
export function copyRow(w: Uint16Array, r: BgChangeRow, k: number) {
  const [sx8, sy8] = r.sources[k]
  const dx = r.x >> 1
  const dy = r.y >> 1
  const sx = sx8 >> 1
  const sy = sy8 >> 1
  for (let j = 0; j < r.h >> 1; j++) {
    for (let i = 0; i < r.w >> 1; i++) {
      const tx = sx + i
      const ty = sy + j
      const v = tx < TILES && ty < TILES ? w[ty * TILES + tx] : 0
      const x = dx + i
      const y = dy + j
      if (x < TILES && y < TILES) w[y * TILES + x] = v
    }
  }
}

/** The tile words with every row copied that `source` names a source for
 *  (-1: none), in id order. */
export function storyWords(base: Uint16Array, rows: BgChangeRow[], source: (r: BgChangeRow) => number): Uint16Array {
  const w = base.slice()
  for (const r of [...rows].sort((a, b) => a.id - b.id)) {
    const k = source(r)
    if (k >= 0 && k < r.sources.length) copyRow(w, r, k)
  }
  return w
}

/** A rectangle on the map, in pixels: [x, y, w, h]. */
export type Rect = [number, number, number, number]

export function rowRect(r: BgChangeRow): Rect {
  return [r.x * 8, r.y * 8, r.w * 8, r.h * 8]
}
