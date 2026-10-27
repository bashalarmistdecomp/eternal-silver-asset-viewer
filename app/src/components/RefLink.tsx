import { createElement, useState } from 'react'
import type { LinkGroup, LinkItem } from '../lib/api'
import { nav } from '../lib/nav'
import { kindIcon, refKey } from '../lib/refs'
import { cn } from '../lib/utils'

/** A kind's icon (lib/refs.ts). */
export function KindIcon({ kind, className }: { kind: string; className?: string }) {
  return createElement(kindIcon(kind), { className })
}

/** A link to a thing: its kind's icon, its title, its number. Following it
 *  opens the thing's card. `hex` adds the number in hex (Advanced mode). */
export function RefLink({ link, disc, hex, className }: { link: LinkItem; disc: string; hex?: boolean; className?: string }) {
  const named = link.title !== link.written
  const tip = [link.title, named ? link.written : '', hex ? link.hex : '', link.note].filter(Boolean).join(' · ')
  return (
    <button
      title={tip}
      onClick={() => nav.open(link.ref, disc)}
      className={cn(
        'max-w-full inline-flex items-center gap-1.5 h-6 px-1.5 rounded border border-border bg-background text-[11px] text-left cursor-pointer',
        'hover:border-primary/50 hover:text-primary transition-colors',
        className,
      )}
    >
      <KindIcon kind={link.ref.kind} className="w-3 h-3 shrink-0 text-muted-foreground" />
      <span className="truncate">{link.title}</span>
      {named && <span className="shrink-0 font-mono text-[10px] text-muted-foreground">{hex ? link.hex : link.written}</span>}
    </button>
  )
}

/** The first links of a group shown, on a card and in the Inspector; the
 *  rest wait behind "Show all". */
const SHOWN = 12
const SHOWN_DENSE = 4

/** A thing's links, grouped: what it points at, then what points at it. */
export function LinkGroups({ groups, disc, hex, dense }: { groups: LinkGroup[]; disc: string; hex?: boolean; dense?: boolean }) {
  return (
    <div className={dense ? 'space-y-2.5' : 'space-y-3'}>
      {groups.map((g) => (
        <Group key={`${g.dir}:${g.title}`} group={g} disc={disc} hex={hex} shown={dense ? SHOWN_DENSE : SHOWN} />
      ))}
    </div>
  )
}

function Group({ group, disc, hex, shown: first }: { group: LinkGroup; disc: string; hex?: boolean; shown: number }) {
  const [all, setAll] = useState(false)
  const shown = all ? group.links : group.links.slice(0, first)
  return (
    <div>
      <h4 className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground mb-1">
        {group.title}
        <span className="ml-1.5 font-normal normal-case tracking-normal">{group.links.length}</span>
      </h4>
      <div className="flex flex-wrap gap-1">
        {shown.map((l) => (
          <RefLink key={refKey(l.ref)} link={l} disc={disc} hex={hex} />
        ))}
        {group.links.length > first && (
          <button className="h-6 px-1.5 text-[11px] text-primary hover:underline cursor-pointer" onClick={() => setAll((a) => !a)}>
            {all ? 'Show fewer' : `Show all ${group.links.length}`}
          </button>
        )}
      </div>
    </div>
  )
}
