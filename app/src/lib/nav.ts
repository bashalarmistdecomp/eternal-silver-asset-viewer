// Following links is a history, as in a browser (docs/taxonomy.md, "How a
// link works"): every card opened and every "Open in" is an entry, and
// Back / Forward (Alt+← / Alt+→, the mouse's side buttons) walk them, so
// no link strands you.
//
// A place is a row of a tab. Browsing a tab's list does not add entries:
// it updates the place you are on, as a page's own scrolling does not add
// to a browser's history. Opening a card adds the place you are on first,
// so Back returns to it.

import { useSyncExternalStore } from 'react'
import type { Ref } from './api'
import { refKey } from './refs'

export interface PlaceEntry {
  type: 'place'
  tab: number
  view: string | null
  item: number
  version: number
}

export interface CardEntry {
  type: 'card'
  ref: Ref
  /** The disc it is read from, by tag. */
  disc: string
}

export type NavEntry = PlaceEntry | CardEntry

interface NavState {
  current: NavEntry | null
  canBack: boolean
  canForward: boolean
}

let entries: NavEntry[] = []
let at = -1
let state: NavState = { current: null, canBack: false, canForward: false }
const listeners = new Set<() => void>()

function changed() {
  state = { current: entries[at] ?? null, canBack: at > 0, canForward: at < entries.length - 1 }
  listeners.forEach((l) => l())
}

function same(a: NavEntry | undefined, b: NavEntry): boolean {
  if (!a || a.type !== b.type) return false
  if (a.type === 'card' && b.type === 'card') return refKey(a.ref) === refKey(b.ref) && a.disc === b.disc
  if (a.type === 'place' && b.type === 'place')
    return a.tab === b.tab && a.view === b.view && a.item === b.item && a.version === b.version
  return false
}

function push(e: NavEntry) {
  if (same(entries[at], e)) return
  entries = [...entries.slice(0, at + 1), e]
  at = entries.length - 1
}

export const nav = {
  /** Where the person is now: a row they selected. Replaces the place
   *  they were on (keeping what Forward leads to); a first entry starts
   *  the history. Ignored while a card is open. */
  here(p: Omit<PlaceEntry, 'type'>) {
    const e: PlaceEntry = { type: 'place', ...p }
    const cur = entries[at]
    if (cur?.type === 'card') return
    if (same(cur, e)) return
    if (cur?.type === 'place') entries = entries.map((x, i) => (i === at ? e : x))
    else push(e)
    changed()
  },
  /** Follow a link: open the thing's card. */
  open(ref: Ref, disc: string) {
    push({ type: 'card', ref, disc })
    changed()
  },
  /** Go to a row: a card's "Open in". */
  go(p: Omit<PlaceEntry, 'type'>) {
    push({ type: 'place', ...p })
    changed()
  },
  back() {
    if (at <= 0) return
    at--
    changed()
  },
  forward() {
    if (at >= entries.length - 1) return
    at++
    changed()
  },
  /** Close the cards: back to the place before them. Forward opens them
   *  again. */
  close() {
    let i = at
    while (i >= 0 && entries[i].type === 'card') i--
    if (i < 0) {
      // cards with no place before them: drop them
      entries = entries.slice(at + 1)
      at = -1
    } else at = i
    changed()
  },
  /** Another game: a new history. */
  reset() {
    entries = []
    at = -1
    changed()
  },
}

export function useNav(): NavState {
  return useSyncExternalStore(
    (fn) => {
      listeners.add(fn)
      return () => listeners.delete(fn)
    },
    () => state,
  )
}

/** Whether a card is open: the views' own keys wait while it is. */
export function isCardOpen(): boolean {
  return state.current?.type === 'card'
}
