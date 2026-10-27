// A view's music buttons (a map's, a fight's) and the card of a song, a
// voice or a sound effect play it from the row that is its home (Music,
// Voices, Sound effects): the disc view does that (DiscView's playSong),
// and hands it down through this context.

import { createContext, useContext } from 'react'
import type { LinkItem, Ref, Result } from './api'

/** Play `song` (a song, a voice or a sound effect), read from disc
 *  `disc`; the one already loaded pauses or resumes instead. */
export type PlaySong = (song: Ref, title: string, disc?: string) => Promise<void>

/** The kinds a card can play: their home row's result has the sound. */
const PLAYABLE = new Set(['song', 'voice', 'sound-effect'])

export function playable(kind: string): boolean {
  return PLAYABLE.has(kind)
}

export const PlaySongContext = createContext<PlaySong | null>(null)

export function usePlaySong(): PlaySong | null {
  return useContext(PlaySongContext)
}

/** The songs a result links to (a map's music, a fight's), each once. */
export function songsOf(result: Result | null | undefined): LinkItem[] {
  const out: LinkItem[] = []
  const seen = new Set<number>()
  for (const g of result?.links ?? []) {
    if (g.dir !== 'out') continue
    for (const l of g.links) {
      if (l.ref.kind !== 'song' || seen.has(l.ref.id[0])) continue
      seen.add(l.ref.id[0])
      out.push(l)
    }
  }
  return out
}
