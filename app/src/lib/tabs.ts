// How each tab (backend/viewer_tabs/tab_providers.py) appears in the rail.
//
// Keyed by the tab's stable key (a provider's `key`); the tab NAMES are the
// providers' own. There are two rails, one per mode (docs/taxonomy.md, "Two
// modes"): Fan mode lays the game out as a fan wiki does and shows the tabs
// a player's things live in; Advanced mode shows every tab, by kind of
// asset. Both are the same tabs: only the arrangement differs.

import {
  Archive,
  AudioLines,
  AudioWaveform,
  Backpack,
  Disc3,
  Film,
  Flag,
  FolderTree,
  Images,
  Info,
  LayoutTemplate,
  Map,
  MessagesSquare,
  MicVocal,
  Monitor,
  Music,
  PersonStanding,
  Shapes,
  Skull,
  SquareUser,
  Sword,
  Swords,
  TextQuote,
  Users,
  WandSparkles,
  type LucideIcon,
} from 'lucide-react'
import type { TabMeta } from './api'

export const TAB_ICONS: Record<string, LucideIcon> = {
  disc: Info,
  'disc-files': FolderTree,
  resources: Archive,
  'cd-tracks': Disc3,
  maps: Map,
  characters: Users,
  monsters: Skull,
  portraits: SquareUser,
  sprites: PersonStanding,
  dialogue: MessagesSquare,
  movies: Film,
  'story-flags': Flag,
  items: Backpack,
  magic: WandSparkles,
  battles: Sword,
  music: Music,
  voices: MicVocal,
  'sound-effects': AudioWaveform,
  'sound-banks': AudioLines,
  bromides: Images,
  menus: LayoutTemplate,
  screens: Monitor,
  'data-tables': Swords,
  strings: TextQuote,
}

export function tabIcon(key: string): LucideIcon {
  return TAB_ICONS[key] ?? Shapes
}

export type RailMode = 'fan' | 'advanced'

type Rail = { label: string; keys: string[] }[]

// A key no tab has yet is skipped, so a tab joins its rail the day it
// exists. Tabs marked "for now" hold what a tab still to come will.
const RAILS: Record<RailMode, Rail> = {
  fan: [
    { label: 'World', keys: ['maps'] },
    { label: 'Cast', keys: ['characters', 'monsters', 'portraits', 'sprites'] },
    { label: 'Story', keys: ['dialogue', 'movies', 'story-flags'] },
    { label: 'Adventure', keys: ['items', 'magic', 'battles'] },
    { label: 'Sound', keys: ['music', 'voices', 'sound-effects'] },
    { label: 'Art', keys: ['bromides', 'menus', 'screens'] },
  ],
  advanced: [
    { label: 'Disc', keys: ['disc', 'disc-files', 'resources', 'cd-tracks'] },
    { label: 'Graphics', keys: ['maps', 'sprites', 'portraits', 'bromides', 'screens', 'menus'] },
    { label: 'Audio', keys: ['music', 'sound-banks', 'voices', 'sound-effects'] },
    { label: 'Video', keys: ['movies'] },
    { label: 'Text', keys: ['dialogue', 'strings'] },
    { label: 'Data', keys: ['data-tables', 'story-flags', 'battles', 'characters', 'monsters', 'items', 'magic'] },
  ],
}

/**
 * The open game's tabs in the rail's order for `mode`, grouped; empty
 * groups are dropped. A tab Advanced mode does not place shows under
 * "More"; Fan mode leaves it out. A game Fan mode has nothing for (a disc
 * with only the PlayStation-generic tabs) gets the Advanced rail.
 */
export function groupTabs(tabs: TabMeta[], mode: RailMode): { label: string; tabs: TabMeta[] }[] {
  const byKey = new globalThis.Map(tabs.map((t) => [t.key, t]))
  const placed = new Set<string>()
  const out = RAILS[mode].map((g) => ({
    label: g.label,
    tabs: g.keys.flatMap((k) => {
      const t = byKey.get(k)
      if (!t) return []
      placed.add(k)
      return [t]
    }),
  }))
  if (mode === 'fan' && placed.size === 0) return groupTabs(tabs, 'advanced')
  const rest = tabs.filter((t) => !placed.has(t.key))
  if (mode === 'advanced' && rest.length) out.push({ label: 'More', tabs: rest })
  return out.filter((g) => g.tabs.length > 0)
}

/** Whether `mode`'s rail has a place for tab `key`. */
export function inRail(key: string, mode: RailMode): boolean {
  return RAILS[mode].some((g) => g.keys.includes(key))
}

/** The tabs of `mode`'s rail, in its order. */
export function railOrder(tabs: TabMeta[], mode: RailMode): TabMeta[] {
  return groupTabs(tabs, mode).flatMap((g) => g.tabs)
}

/** The view a tab opens on the first time it is shown: its technical
 *  view in Advanced mode, where it has one. */
export function firstView(tab: TabMeta, mode: RailMode): string | null {
  if (mode === 'advanced' && tab.technicalView && tab.views.includes(tab.technicalView)) return tab.technicalView
  return tab.view
}

/** What a game not read in full yet (Slot.partial) opens with, said on its
 *  library card and on its banner once open. */
export const PARTIAL =
  "For now it shows only what any PlayStation disc has: its movies, and in Advanced mode (ADV) the disc, its files and its CD tracks. Its maps, characters, story and music can't be read yet."

/** For the providers without a docstring of their own. */
export const TAB_BLURB: Record<string, string> = {
  menus: 'Interface graphics: SYSTEM.DAT, OPEN1.BIN, MENU.BIN and STFIELD.DAT, one entry per layer.',
  portraits: 'Character face portraits from the FACE blocks in LUNADATA.FIL, with an atlas of every one first.',
}
