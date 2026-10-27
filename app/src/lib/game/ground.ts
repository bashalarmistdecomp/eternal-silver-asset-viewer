// A map's ground drawn as the game draws it, from the map's own data:
// the tile words (the type-5 layout as one 128 x 128 plane), the 8-bit
// texture pages and the CLUT rows as colour words (backend
// viewer_tabs/field_view.py `ground_data`).
//
// bg_first_draw (0x80014058) draws each 16 x 16 cell from its word: page
// bits 8..9, u = (word & 0xF) * 16, v = word & 0xF0, CLUT row 500 or 501
// by bit 12, mirrored by bits 14 and 15. A word with bit 13 is drawn a
// second time through the cover rows 510 / 511: the roof's copy, which
// the field draw puts over a sprite standing under it (fieldScene.ts).
//
// The second layer, when it is drawn behind the tiles, is its 512 x 1024
// plane of row-508 colour indexes tiled over the map, black where it
// draws nothing.
//
// What changes at run time changes here the way the game changes it:
// tile_animation_load (0x80026814) writes new texels into the pages, so
// every cell reading those tiles changes with them; a bg change copies
// tile words (the cells re-read their tiles); palette_update (0x80020134)
// re-sends row 501 (the colours of every pixel drawn through it change)
// and copies a palette animation's CLUTs of it to row 508 (the second
// layer's). Only the cells touched are drawn again.

import { blobUrl } from '../backend'
import type { FieldGround } from '../api'

export const CELL = 16
const TILES = 128
const PLANE = TILES * CELL
/** No texel: the cell reads outside its page, or its row is not loaded. */
const NONE = 0xffff
const STP = 0x8000
const ROOF = 0x2000
const BLACK = 0xff000000
/** Cells are pushed to the canvases a block at a time. */
const BLOCK_CELLS = 16
const BLOCKS = TILES / BLOCK_CELLS

/** A colour word as the GPU draws it, packed for a little-endian
 *  Uint32Array view of ImageData: 5 bits a channel shifted up by 3 (the
 *  backend's world_map.words_rgba), alpha 0 only for the word 0. */
function rgba(w: number): number {
  if (w === 0) return 0
  return (0xff000000 | (((w >> 10) & 31) << 19) | (((w >> 5) & 31) << 11) | ((w & 31) << 3)) >>> 0
}

/** Half and half (semi-transparency mode 0), over nothing: half alpha. */
function half(under: number, over: number): number {
  if (under >>> 24 === 0) return ((over & 0x00ffffff) | 0x80000000) >>> 0
  const r = ((under & 0xff) + (over & 0xff)) >> 1
  const g = (((under >> 8) & 0xff) + ((over >> 8) & 0xff)) >> 1
  const b = (((under >> 16) & 0xff) + ((over >> 16) & 0xff)) >> 1
  return (0xff000000 | (b << 16) | (g << 8) | r) >>> 0
}

export interface TileSeed {
  delay: number
  frames: number
  count: number
  tile: number
  source: number
}

export class Ground {
  readonly blend: boolean
  /** The tile words as the map loads them, and as they stand. */
  readonly baseWords: Uint16Array
  words: Uint16Array
  private pages: (Uint8Array | null)[] = [null, null, null, null]
  private basePages: (Uint8Array | null)[] = [null, null, null, null]
  private pageW = [0, 0, 0, 0]
  private pageH = [0, 0, 0, 0]
  /** CLUT rows 500 / 501 and 510 / 511 as colour words. */
  rows: Uint16Array[]
  private cover: Uint16Array[]
  private lut: Uint32Array[]
  private coverLut: Uint32Array[]
  private tileImages: Uint8Array
  private seeds: TileSeed[]
  /** Each record's frame on the pages: -1 while they hold their own texels. */
  private frames: number[]
  /** Per pixel: the CLUT row << 8 | the texel, or NONE. */
  private src = new Uint16Array(PLANE * PLANE)
  /** Per cell: which colours of each row its pixels read, 512 bits. */
  private uses = new Uint32Array(TILES * TILES * 16)
  /** Cells by the page tile they read (word & 0x3FF). */
  private byTile = new Map<number, number[]>()
  private under: Uint32Array | null = null
  /** The second layer: its indexes, size, row 508 and the CLUTs of row
   *  501 copied into it every frame; per 16 x 16 cell of it, which
   *  indexes the cell holds (256 bits). */
  private l2: Uint8Array | null = null
  private l2W = 0
  private l2H = 0
  private l2Row = new Uint16Array(256)
  private l2Lut = new Uint32Array(256)
  private l2Uses = new Uint32Array(0)
  private copy: [number, number] | null
  private ground: ImageData
  private roof: ImageData
  private roofStp: ImageData | null
  private g32: Uint32Array
  private r32: Uint32Array
  private rs32: Uint32Array | null
  /** Cells to draw again: bit 1 the ground, bit 2 the roof copies. */
  private dirty = new Uint8Array(TILES * TILES)
  private anyDirty = false
  private showBack = true
  private showTiles = true
  readonly groundCanvas: HTMLCanvasElement
  readonly roofCanvas: HTMLCanvasElement
  readonly roofStpCanvas: HTMLCanvasElement | null
  readonly hasUnder: boolean

  private constructor(data: FieldGround, bytes: ArrayBuffer) {
    const part = (name: string) => {
      const [at, n] = data.parts[name] ?? [0, 0]
      return new Uint8Array(bytes, at, n)
    }
    const w = part('words')
    this.baseWords = new Uint16Array(TILES * TILES)
    const dv = new DataView(w.buffer, w.byteOffset, w.byteLength)
    for (let i = 0; i < TILES * TILES && i * 2 + 1 < w.byteLength; i++) this.baseWords[i] = dv.getUint16(i * 2, true)
    this.words = this.baseWords.slice()
    for (const p of data.pages) {
      const raw = part(p.part)
      this.basePages[p.page] = raw.slice()
      this.pages[p.page] = raw.slice()
      this.pageW[p.page] = p.w
      this.pageH[p.page] = p.h
    }
    this.rows = data.rows.map((r) => Uint16Array.from(r))
    this.cover = data.cover.map((r) => Uint16Array.from(r))
    this.lut = this.rows.map((r) => Uint32Array.from(r, rgba))
    this.coverLut = this.cover.map((r) => Uint32Array.from(r, rgba))
    this.tileImages = part('tileImages').slice()
    this.seeds = data.tiles
    this.frames = data.tiles.map(() => -1)
    this.blend = data.blend
    this.copy = data.palette?.copy ?? null
    this.hasUnder = !!data.layer2
    if (data.layer2) this.layer2(part(data.layer2.part), data.layer2)
    const canvas = () => {
      const c = document.createElement('canvas')
      c.width = PLANE
      c.height = PLANE
      return c
    }
    this.groundCanvas = canvas()
    this.roofCanvas = canvas()
    this.roofStpCanvas = this.blend ? canvas() : null
    this.ground = new ImageData(PLANE, PLANE)
    this.roof = new ImageData(PLANE, PLANE)
    this.roofStp = this.blend ? new ImageData(PLANE, PLANE) : null
    this.g32 = new Uint32Array(this.ground.data.buffer)
    this.r32 = new Uint32Array(this.roof.data.buffer)
    this.rs32 = this.roofStp ? new Uint32Array(this.roofStp.data.buffer) : null
    for (let k = 0; k < TILES * TILES; k++) {
      this.readCell(k)
      this.byTileAdd(k, this.words[k])
    }
    this.dirty.fill(3)
    this.anyDirty = true
    this.flush()
  }

  static async load(data: FieldGround): Promise<Ground> {
    const r = await fetch(blobUrl(data.blob, 'bin'))
    if (!r.ok) throw new Error(`the ground's bytes did not load (${r.status})`)
    return new Ground(data, await r.arrayBuffer())
  }

  /** The second layer's plane and row 508, and the picture of it tiled. */
  private layer2(idx: Uint8Array, l2: NonNullable<FieldGround['layer2']>) {
    this.l2 = idx.slice()
    this.l2W = l2.w
    this.l2H = l2.h
    this.l2Row = Uint16Array.from(l2.row)
    this.l2Lut = Uint32Array.from(this.l2Row, rgba)
    const cw = l2.w / CELL
    const ch = l2.h / CELL
    this.l2Uses = new Uint32Array(cw * ch * 8)
    for (let y = 0; y < l2.h; y++) {
      for (let x = 0; x < l2.w; x++) {
        const v = this.l2[y * l2.w + x]
        if (v) this.l2Uses[(((y / CELL) | 0) * cw + ((x / CELL) | 0)) * 8 + (v >> 5)] |= 1 << (v & 31)
      }
    }
    this.under = new Uint32Array(PLANE * PLANE)
    for (let c = 0; c < cw * ch; c++) this.l2Cell(c)
  }

  /** Second-layer cell c drawn again wherever it is tiled over the plane;
   *  the plane cells it lies under are marked. */
  private l2Cell(c: number) {
    const { l2, l2W, l2H, l2Lut, under } = this
    const cw = l2W / CELL
    const x0 = (c % cw) * CELL
    const y0 = ((c / cw) | 0) * CELL
    for (let oy = 0; oy < PLANE; oy += l2H) {
      for (let ox = 0; ox < PLANE; ox += l2W) {
        for (let j = 0; j < CELL; j++) {
          const from = (y0 + j) * l2W + x0
          const to = (oy + y0 + j) * PLANE + ox + x0
          for (let i = 0; i < CELL; i++) {
            const v = l2![from + i]
            under![to + i] = v ? l2Lut[v] : BLACK
          }
        }
        this.mark(((oy + y0) / CELL) * TILES + (ox + x0) / CELL, 1)
      }
    }
  }

  /** Is cell k a roof (its word queued a second time)? */
  isRoof(k: number): boolean {
    return (this.words[k] & ROOF) !== 0
  }

  /** The cell's pixels as its word reads them from the pages. */
  private readCell(k: number) {
    const word = this.words[k]
    const cx = k % TILES
    const cy = (k / TILES) | 0
    const page = (word >> 8) & 3
    const u = (word & 0xf) * CELL
    const v = word & 0xf0
    const row = (word >> 12) & 1
    const hflip = (word & 0x4000) !== 0
    const vflip = (word & 0x8000) !== 0
    const pix = this.pages[page]
    const pw = this.pageW[page]
    const ok = !!pix && row < this.rows.length && u + CELL <= pw && v + CELL <= this.pageH[page]
    const uses = this.uses
    const ub = k * 16
    uses.fill(0, ub, ub + 16)
    const tag = row << 8
    for (let j = 0; j < CELL; j++) {
      const at = (cy * CELL + j) * PLANE + cx * CELL
      const sy = v + (vflip ? CELL - 1 - j : j)
      for (let i = 0; i < CELL; i++) {
        if (!ok) {
          this.src[at + i] = NONE
          continue
        }
        const t = pix![sy * pw + u + (hflip ? CELL - 1 - i : i)]
        const c = tag | t
        this.src[at + i] = c
        uses[ub + (c >> 5)] |= 1 << (c & 31)
      }
    }
  }

  private byTileAdd(k: number, word: number) {
    const key = word & 0x3ff
    let list = this.byTile.get(key)
    if (!list) this.byTile.set(key, (list = []))
    list.push(k)
  }

  private byTileDrop(k: number, word: number) {
    const list = this.byTile.get(word & 0x3ff)
    if (!list) return
    const at = list.indexOf(k)
    if (at >= 0) list.splice(at, 1)
  }

  private mark(k: number, how: number) {
    this.dirty[k] |= how
    this.anyDirty = true
  }

  /** Show or hide the second layer and the tiles: every cell is drawn again. */
  layers(back: boolean, tiles: boolean) {
    if (back === this.showBack && tiles === this.showTiles) return
    this.showBack = back
    this.showTiles = tiles
    this.dirty.fill(1)
    this.anyDirty = true
  }

  /** Put tile words in place (a bg change, or its undoing); the cells
   *  whose word changed read their tiles again. */
  setWords(next: Uint16Array) {
    for (let k = 0; k < TILES * TILES; k++) {
      if (next[k] === this.words[k]) continue
      this.byTileDrop(k, this.words[k])
      this.words[k] = next[k]
      this.byTileAdd(k, next[k])
      this.readCell(k)
      this.mark(k, 3)
    }
  }

  /** Set a CLUT row's colours (palette_update's re-send of row 501). */
  setRow(row: number, words: Uint16Array) {
    const cur = this.rows[row]
    if (!cur) return
    const changed = new Uint32Array(16)
    let any = false
    for (let i = 0; i < 256; i++) {
      if (cur[i] === words[i]) continue
      cur[i] = words[i]
      this.lut[row][i] = rgba(words[i])
      const c = (row << 8) | i
      changed[c >> 5] |= 1 << (c & 31)
      any = true
    }
    if (!any) return
    if (row === 1) this.copyToLayer2(words)
    // the cover rows are not re-sent: the roofs' copies keep their colours
    for (let k = 0; k < TILES * TILES; k++) {
      const b = k * 16
      for (let x = 0; x < 16; x++) {
        if (this.uses[b + x] & changed[x]) {
          this.mark(k, 1)
          break
        }
      }
    }
  }

  /** palette_update's copy of row 501's CLUTs `copy` to row 508: bit 15
   *  set, colour 0 of each CLUT 0 (world_map.layer2_cluts); the second
   *  layer's cells holding a changed colour are drawn again. */
  private copyToLayer2(row1: Uint16Array) {
    if (!this.l2 || !this.copy) return
    const [first, count] = this.copy
    const changed = new Uint32Array(8)
    let any = false
    for (let n = Math.max(first, 0); n < Math.min(first + count, 16); n++) {
      for (let i = 1; i < 16; i++) {
        const c = n * 16 + i
        const w = row1[c] | STP
        if (this.l2Row[c] === w) continue
        this.l2Row[c] = w
        this.l2Lut[c] = rgba(w)
        changed[c >> 5] |= 1 << (c & 31)
        any = true
      }
    }
    if (!any) return
    const cells = this.l2Uses.length / 8
    for (let c = 0; c < cells; c++) {
      for (let x = 0; x < 8; x++) {
        if (this.l2Uses[c * 8 + x] & changed[x]) {
          this.l2Cell(c)
          break
        }
      }
    }
  }

  /** The tile animations as they stand `t` field frames after the map
   *  loads: a record steps every max(delay, 1) frames (tile_animation_step
   *  (0x80026690)) and, from its first step, frame (steps mod frames) of
   *  its images is on the page. */
  setTick(t: number) {
    this.seeds.forEach((r, n) => {
      const steps = Math.floor(t / Math.max(r.delay, 1))
      const frame = steps === 0 ? -1 : r.frames > 0 ? steps % r.frames : 0
      if (frame === this.frames[n]) return
      this.frames[n] = frame
      for (let j = 0; j < r.count; j++) {
        const tile = (r.tile + j) & 0x3ff
        const page = (tile >> 8) & 3
        const u = (tile & 0xf) * CELL
        const v = tile & 0xf0
        const pix = this.pages[page]
        const pw = this.pageW[page]
        if (!pix || u + CELL > pw || v + CELL > this.pageH[page]) continue
        const from = frame < 0 ? null : (r.source + frame * r.count + j) * 0x100
        if (from !== null && from + 0x100 > this.tileImages.length) continue
        for (let line = 0; line < CELL; line++) {
          const o = (v + line) * pw + u
          if (from === null) pix.set(this.basePages[page]!.subarray(o, o + CELL), o)
          else pix.set(this.tileImages.subarray(from + line * CELL, from + line * CELL + CELL), o)
        }
        for (const k of this.byTile.get(tile) ?? []) {
          this.readCell(k)
          this.mark(k, 3)
        }
      }
    })
  }

  /** Draw the dirty cells and push them to the canvases. */
  flush() {
    if (!this.anyDirty) return
    this.anyDirty = false
    const gctx = this.groundCanvas.getContext('2d')!
    const rctx = this.roofCanvas.getContext('2d')!
    const sctx = this.roofStpCanvas?.getContext('2d')
    for (let by = 0; by < BLOCKS; by++) {
      for (let bx = 0; bx < BLOCKS; bx++) {
        let g = [PLANE, PLANE, -1, -1]
        let r = [PLANE, PLANE, -1, -1]
        for (let y = by * BLOCK_CELLS; y < (by + 1) * BLOCK_CELLS; y++) {
          for (let x = bx * BLOCK_CELLS; x < (bx + 1) * BLOCK_CELLS; x++) {
            const k = y * TILES + x
            const d = this.dirty[k]
            if (!d) continue
            this.dirty[k] = 0
            if (d & 1) {
              this.drawGround(x, y)
              g = grow(g, x, y)
            }
            if (d & 2) {
              this.drawRoof(k, x, y)
              r = grow(r, x, y)
            }
          }
        }
        if (g[2] >= 0) put(gctx, this.ground, g)
        if (r[2] >= 0) {
          put(rctx, this.roof, r)
          if (sctx && this.roofStp) put(sctx, this.roofStp, r)
        }
      }
    }
  }

  private drawGround(cx: number, cy: number) {
    const { src, g32, under, blend } = this
    const back = this.showBack && under
    const tiles = this.showTiles
    for (let j = 0; j < CELL; j++) {
      const at = (cy * CELL + j) * PLANE + cx * CELL
      for (let p = at; p < at + CELL; p++) {
        let out = back ? under![p] : 0
        const s = src[p]
        if (tiles && s !== NONE) {
          const w = this.rows[s >> 8][s & 0xff]
          if (w !== 0) out = blend && w & STP ? half(out, this.lut[s >> 8][s & 0xff]) : this.lut[s >> 8][s & 0xff]
        }
        g32[p] = out
      }
    }
  }

  private drawRoof(k: number, cx: number, cy: number) {
    const { src, r32, rs32 } = this
    const roof = this.isRoof(k)
    for (let j = 0; j < CELL; j++) {
      const at = (cy * CELL + j) * PLANE + cx * CELL
      for (let p = at; p < at + CELL; p++) {
        r32[p] = 0
        if (rs32) rs32[p] = 0
        const s = src[p]
        if (!roof || s === NONE) continue
        const row = s >> 8
        const w = this.cover[row]?.[s & 0xff] ?? 0
        if (w === 0) continue
        const c = this.coverLut[row][s & 0xff]
        if (rs32 && w & STP) rs32[p] = c
        else r32[p] = c
      }
    }
  }
}

function grow(b: number[], x: number, y: number): number[] {
  return [Math.min(b[0], x), Math.min(b[1], y), Math.max(b[2], x), Math.max(b[3], y)]
}

function put(ctx: CanvasRenderingContext2D, data: ImageData, b: number[]) {
  const x = b[0] * CELL
  const y = b[1] * CELL
  ctx.putImageData(data, 0, 0, x, y, (b[2] - b[0] + 1) * CELL, (b[3] - b[1] + 1) * CELL)
}
