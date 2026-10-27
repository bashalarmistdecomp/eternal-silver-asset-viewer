// A thing of the game, pointed at: its kind and its number (backend
// viewer_tabs/refs.py, docs/taxonomy.md). Each kind has an icon, shown
// beside every link to one.

import {
  Archive,
  AudioLines,
  AudioWaveform,
  Backpack,
  Blocks,
  Boxes,
  Clapperboard,
  Disc3,
  DoorOpen,
  File,
  FileMusic,
  Flag,
  Footprints,
  Gem,
  Grid3x3,
  Hand,
  Image,
  Images,
  Layers,
  Library,
  Map,
  MapPin,
  MessageSquare,
  MicVocal,
  Music,
  PersonStanding,
  ScrollText,
  Shapes,
  Skull,
  Sparkles,
  SquareUser,
  Store,
  Sword,
  Swords,
  Tag,
  TextQuote,
  User,
  Users,
  Volume2,
  WandSparkles,
  Zap,
  type LucideIcon,
} from 'lucide-react'
import type { LinkGroup, LinkItem, Ref } from './api'

const KIND_ICONS: Record<string, LucideIcon> = {
  map: Map,
  place: MapPin,
  entrance: DoorOpen,
  'party-move': Footprints,
  'tile-change': Blocks,
  cell: Grid3x3,
  'story-flag': Flag,
  'object-set': Boxes,
  entity: User,
  trigger: Hand,
  'map-monster': Skull,
  chest: Gem,
  actor: Clapperboard,
  character: Users,
  portrait: SquareUser,
  'portrait-list': SquareUser,
  sprite: PersonStanding,
  'battle-sprite': PersonStanding,
  message: MessageSquare,
  script: ScrollText,
  label: Tag,
  movie: Clapperboard,
  bromide: Images,
  item: Backpack,
  shop: Store,
  spell: WandSparkles,
  battle: Swords,
  'scripted-battle': Swords,
  monster: Skull,
  'monster-attack': Zap,
  'monster-set': Layers,
  'monster-group': Users,
  'battle-effect': Sparkles,
  song: Music,
  voice: MicVocal,
  'sound-effect': AudioWaveform,
  'sound-bank': Library,
  sequence: FileMusic,
  sample: AudioLines,
  'sound-area': Volume2,
  image: Image,
  icon: Shapes,
  'disc-file': File,
  resource: Archive,
  'cd-track': Disc3,
  string: TextQuote,
}

export function kindIcon(kind: string): LucideIcon {
  return KIND_ICONS[kind] ?? (kind.includes('battle') ? Sword : Shapes)
}

/** "map:21": a key for maps and lists. */
export function refKey(ref: Ref): string {
  return `${ref.kind}:${ref.id.join('/')}`
}

/** A thing's links parted for Fan mode: the groups as they show, and the
 *  links marked `advanced`, which Fan mode shows with the extended info:
 *  those to kinds whose home is only in Advanced mode (a resource, a sound
 *  bank) and those of the code's own groups (a story flag's Held in and
 *  Goes on at). Each part keeps the groups' order and titles; an emptied
 *  group is dropped. */
export function splitAdvanced(groups: LinkGroup[]): { plain: LinkGroup[]; advanced: LinkGroup[] } {
  const part = (keep: (l: LinkItem) => boolean) =>
    groups.map((g) => ({ ...g, links: g.links.filter(keep) })).filter((g) => g.links.length > 0)
  return { plain: part((l) => !l.advanced), advanced: part((l) => !!l.advanced) }
}
