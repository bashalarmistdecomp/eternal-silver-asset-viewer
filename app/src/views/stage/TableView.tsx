import { ArrowDown, ArrowUp } from 'lucide-react'
import { useMemo, useState } from 'react'
import { cn } from '../../lib/utils'

const NUMERIC = /^-?(0x[0-9a-f]+|\d+(\.\d+)?)$/i

function num(v: string): number {
  return v.toLowerCase().startsWith('0x') || v.startsWith('-0x') ? parseInt(v, 16) : Number(v)
}

type Group = { label: string; span: number; tone?: 'ok' | 'muted' }

/**
 * A record table (the battle tables' `records`), one row per record, with
 * every key any record carries as a column. Sorting is the only thing it
 * adds; the cells are the provider's own values, formatted as its text
 * view formats them. Where the provider groups columns (enemy_templates:
 * the stats the code reads, then the rest of the row), a band above the header
 * says which is which, and each header's tooltip is its field note.
 */
export function TableView({
  columns,
  rows,
  groups,
  notes,
}: {
  columns: string[]
  rows: string[][]
  groups?: Group[]
  notes?: Record<string, string>
}) {
  const [sort, setSort] = useState<{ col: number; desc: boolean } | null>(null)
  const numeric = useMemo(() => columns.map((_, c) => rows.every((r) => r[c] === '-' || NUMERIC.test(r[c] ?? ''))), [columns, rows])
  const sorted = useMemo(() => {
    if (!sort) return rows
    const { col, desc } = sort
    const out = [...rows].sort((a, b) => {
      const x = a[col] ?? ''
      const y = b[col] ?? ''
      const r = numeric[col] ? (x === '-' ? -Infinity : num(x)) - (y === '-' ? -Infinity : num(y)) : x.localeCompare(y)
      return desc ? -r : r
    })
    return out
  }, [rows, sort, numeric])

  // The group a column starts or sits in, for the dividing borders.
  const starts = useMemo(() => {
    const s = new Set<number>()
    let at = 0
    for (const g of groups ?? []) {
      if (at > 0) s.add(at)
      at += g.span
    }
    return s
  }, [groups])
  const banded = !!groups?.some((g) => g.label)

  return (
    <div className="flex-1 min-h-0 min-w-0 rounded-lg border border-border bg-card shadow-sm overflow-auto selectable">
      <table className="text-[11px] font-mono border-separate border-spacing-0 w-max min-w-full">
        <thead>
          {banded && (
            <tr>
              {groups!.map((g, i) =>
                g.span ? (
                  <th
                    key={i}
                    colSpan={g.span}
                    className={cn(
                      'sticky top-0 z-10 h-6 px-2.5 text-left font-sans text-[10px] font-semibold uppercase tracking-wide whitespace-nowrap border-b border-border',
                      i > 0 && 'border-l-2',
                      g.tone === 'ok' ? 'bg-ok-soft text-ok' : g.tone === 'muted' ? 'bg-muted text-muted-foreground' : 'bg-muted',
                      i === 0 && 'left-0 z-20',
                    )}
                  >
                    {g.label}
                  </th>
                ) : null,
              )}
            </tr>
          )}
          <tr>
            {columns.map((c, i) => (
              <th
                key={c}
                title={notes?.[c]}
                onClick={() => setSort((s) => (s?.col === i ? (s.desc ? null : { col: i, desc: true }) : { col: i, desc: false }))}
                className={cn(
                  'sticky z-10 bg-muted border-b border-border px-2.5 py-1.5 font-semibold text-secondary-foreground cursor-pointer whitespace-nowrap select-none hover:text-primary',
                  banded ? 'top-6' : 'top-0',
                  numeric[i] ? 'text-right' : 'text-left',
                  starts.has(i) && 'border-l-2',
                  notes?.[c] && 'underline decoration-dotted decoration-border underline-offset-4',
                  i === 0 && 'left-0 z-20',
                )}
              >
                <span className="inline-flex items-center gap-1">
                  {c}
                  {sort?.col === i && (sort.desc ? <ArrowDown className="w-3 h-3" /> : <ArrowUp className="w-3 h-3" />)}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((r, ri) => (
            <tr key={ri} className="group">
              {columns.map((_, ci) => (
                <td
                  key={ci}
                  className={cn(
                    'px-2.5 py-1 border-b border-border/50 whitespace-nowrap group-hover:bg-accent/60',
                    ri % 2 ? 'bg-[#fcfaf8]' : 'bg-card',
                    numeric[ci] ? 'text-right tabular-nums' : 'text-left',
                    r[ci] === '-' && 'text-muted-foreground',
                    starts.has(ci) && 'border-l-2 border-l-border',
                    ci === 0 && 'sticky left-0 font-semibold',
                  )}
                >
                  {r[ci]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
