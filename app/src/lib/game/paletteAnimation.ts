// A map's palette animation, stepped as palette_animation_step
// (0x800263F4) steps it once a field frame (backend
// formats/palette_animation.py): slots 0 to 7 in order, each counting
// its timer up to its delay and then changing its colours of row 501.
// The colours at tick t are those after t steps from the map's own, so a
// tick before the last one asked for starts again from the map's own.

import type { FieldPalette, PaletteSlot } from '../api'

const COPY = 1
const UP = 2
const DOWN = 3

interface Slot extends PaletteSlot {
  timer: number
  frame: number
}

export class PaletteAnimator {
  private readonly base: Uint16Array
  private readonly seeds: PaletteSlot[]
  private slots: Slot[] = []
  private row: Uint16Array
  private t = 0

  constructor(base: ArrayLike<number>, palette: FieldPalette) {
    this.base = Uint16Array.from(base)
    this.seeds = palette.slots
    this.row = this.base.slice()
    this.reset()
  }

  private reset() {
    this.row.set(this.base)
    this.slots = this.seeds.map((s) => ({ ...s, timer: 0, frame: 0 }))
    this.t = 0
  }

  /** Row 501 as it stands `t` field frames after the map loads. The array
   *  is the animator's own: read it before the next call. */
  at(t: number): Uint16Array {
    if (t < this.t) this.reset()
    while (this.t < t) {
      this.step()
      this.t++
    }
    return this.row
  }

  private step() {
    const q = this.row
    for (const r of this.slots) {
      r.timer = (r.timer + 1) & 0xff
      if (r.timer < r.delay) continue
      r.timer = 0
      r.frame = (r.frame + 1) & 0xff
      if (r.frame >= r.frames) r.frame = 0
      const first = r.first
      const n = Math.min(r.count, 256 - first)
      if (n <= 0) continue
      if (r.mode === COPY) {
        const at = r.frame * r.count
        for (let i = 0; i < n && at + i < r.strip.length; i++) q[first + i] = r.strip[at + i]
      } else if (r.mode === UP) {
        const t = q[first + n - 1]
        for (let i = n - 1; i > 0; i--) q[first + i] = q[first + i - 1]
        q[first] = t
      } else if (r.mode === DOWN) {
        const t = q[first]
        for (let i = 0; i < n - 1; i++) q[first + i] = q[first + i + 1]
        q[first + n - 1] = t
      }
    }
  }
}
