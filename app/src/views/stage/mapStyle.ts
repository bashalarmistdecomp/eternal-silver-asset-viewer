/** Each group's colour in the map's bar and panels. */
export const GROUP_TONE: Record<string, string> = {
  entities: 'text-sky-300',
  monsters: 'text-rose-300',
  chests: 'text-amber-300',
  party: 'text-emerald-300',
}

export const hex = (n: number, w = 2) => '0x' + n.toString(16).toUpperCase().padStart(w, '0')
