// Actor animation: the engine's three routines, as the backend's reader
// of the tables gives them (sprite_pages.Animation, in
// backend/decoders/plugins/SLUS_006_28/formats/sprite_pages.py):
//
//   BtlAnimationSet(actor, id)   (0x80027208)
//       play: no-op if `id` is already playing; +0x30 = id, then restart
//   BtlAnimationStart(actor, 1)  (0x80027240)
//       restart: step = first, end = first + count (count keeps its bit-15
//       HOLD flag), timer 0, duration = the first step's
//   BtlAnimationStep(...)        (0x800272A8)
//       tick, once per frame for every actor: timer++; when it reaches the
//       step's duration the next step starts — at the end a LOOP restarts, a
//       HOLD stays on its last step — and the drawn pose is that step's pose
//
// The tables are each actor block's own, exported per block. Which id
// plays when is the calling code's choice; this only advances a table.

export interface AnimDef {
  index: number
  hold: boolean
  /** Absolute index of the anim's first step in the block's step table
   *  (sprite_pages.Animation.first; the game's +0x38 counts from it).
   *  Exported by the battle sheets; absent on other tables. */
  first?: number
  /** [pose, duration in ticks] */
  steps: [number, number][]
  /** What the code plays it for, when the battle census names it. */
  name?: string | null
  /** That, in a fan's words (Fan mode's name for it). */
  fanName?: string | null
  /** The function(s) that play it. */
  proof?: string | null
}

const HOLD = 0x8000

export class ActorAnim {
  /** +0x30 current id */
  anim = -1
  /** +0x34 ticks into the current step */
  timer = 0
  /** +0x38, an index into this anim's steps */
  step = 0
  private dur = 0 // +0x36
  private end = 0 // +0x3A, carries the HOLD flag in bit 15
  private readonly table: AnimDef[]

  constructor(table: AnimDef[]) {
    this.table = table
  }

  get def(): AnimDef | undefined {
    return this.table[this.anim]
  }

  /** The pose the current step draws, or 0 with nothing playing. */
  get pose(): number {
    const a = this.def
    return a && a.steps.length ? a.steps[Math.min(this.step, a.steps.length - 1)][0] : 0
  }

  has(id: number): boolean {
    return !!this.table[id] && this.table[id].steps.length > 0
  }

  /** BtlAnimationSet */
  play(id: number): void {
    if (id === this.anim || !this.has(id)) return
    this.anim = id
    this.restart()
  }

  /** Start `id` from its first step even if it is already playing — a
   *  viewer's "play again", not anything the engine does. */
  replay(id: number): void {
    if (!this.has(id)) return
    this.anim = id
    this.restart()
  }

  /** BtlAnimationStart(actor, 1) */
  private restart(): void {
    const a = this.table[this.anim]
    this.step = 0
    this.end = (a.steps.length | (a.hold ? HOLD : 0)) & 0xffff
    this.timer = 0
    this.dur = a.steps[0][1]
  }

  /** One BtlAnimationStep tick. */
  tick(): void {
    const a = this.def
    if (!a || !a.steps.length) return
    if (++this.timer < this.dur) return
    const next = this.step + 1
    if (this.end & HOLD) {
      if (next < (this.end & 0x7fff)) this.step = next // else: stay on the last
    } else if (next >= this.end) {
      this.restart()
      return
    } else {
      this.step = next
    }
    this.timer = 0
    this.dur = a.steps[this.step][1]
  }
}
