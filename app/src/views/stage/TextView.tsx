import { ChevronDown, ChevronUp, Copy, Search, WrapText } from 'lucide-react'
import { Fragment, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useStored } from '../../lib/hooks'
import { cn } from '../../lib/utils'

/** "heading" followed by "-----" or "=====" — the providers' section style. */
function isRule(line: string) {
  return /^\s*([-=])\1{2,}\s*$/.test(line)
}

/**
 * A provider's text, selectable and searchable. Column-aligned text (record
 * tables, hex dumps) is shown unwrapped by default, because wrapping moves
 * every value out from under its header.
 */
export function TextView({ text, wrap: wrapDefault }: { text: string; wrap: boolean }) {
  const [wrapPref, setWrapPref] = useStored<boolean | null>('text.wrap', null)
  const wrap = wrapPref ?? wrapDefault
  const [query, setQuery] = useState('')
  const [hit, setHit] = useState(0)
  const findRef = useRef<HTMLInputElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const lines = useMemo(() => text.split('\n'), [text])

  const matches = useMemo(() => {
    const q = query.toLowerCase()
    if (!q) return [] as number[]
    const out: number[] = []
    lines.forEach((l, i) => {
      if (l.toLowerCase().includes(q)) out.push(i)
    })
    return out
  }, [lines, query])

  useEffect(() => setHit(0), [query, text])
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: 0 })
  }, [text])
  useEffect(() => {
    if (!matches.length) return
    const el = scrollRef.current?.querySelector(`[data-line="${matches[hit % matches.length]}"]`)
    el?.scrollIntoView({ block: 'center' })
  }, [hit, matches])

  useEffect(() => {
    const onFind = () => findRef.current?.focus()
    window.addEventListener('viewer:find', onFind)
    return () => window.removeEventListener('viewer:find', onFind)
  }, [])

  const q = query.toLowerCase()
  const current = matches.length ? matches[hit % matches.length] : -1

  return (
    <div className="flex-1 min-h-0 min-w-0 flex flex-col rounded-lg border border-border bg-card shadow-sm overflow-hidden">
      <div className="h-9 shrink-0 px-2 border-b border-border flex items-center gap-1.5 text-[11px] text-muted-foreground">
        <span className="font-mono px-1">{lines.length.toLocaleString()} lines</span>
        <div className="flex-1" />
        <div className="flex items-center gap-1 h-6 rounded border border-input bg-background px-1.5 focus-within:border-primary">
          <Search className="w-3 h-3" />
          <input
            ref={findRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') setHit((h) => h + (e.shiftKey ? matches.length - 1 : 1))
              if (e.key === 'Escape') {
                setQuery('')
                e.currentTarget.blur()
              }
            }}
            placeholder="Find in text"
            className="w-36 bg-transparent outline-none text-foreground placeholder:text-muted-foreground"
          />
          {query && <span className="font-mono">{matches.length ? `${(hit % matches.length) + 1}/${matches.length}` : '0'}</span>}
        </div>
        <button className="w-6 h-6 rounded hover:bg-muted flex items-center justify-center cursor-pointer disabled:opacity-40" disabled={!matches.length} onClick={() => setHit((h) => h + matches.length - 1)} title="Previous (Shift+Enter)">
          <ChevronUp className="w-3.5 h-3.5" />
        </button>
        <button className="w-6 h-6 rounded hover:bg-muted flex items-center justify-center cursor-pointer disabled:opacity-40" disabled={!matches.length} onClick={() => setHit((h) => h + 1)} title="Next (Enter)">
          <ChevronDown className="w-3.5 h-3.5" />
        </button>
        <button
          className={cn('h-6 px-1.5 rounded flex items-center gap-1 cursor-pointer', wrap ? 'bg-accent text-primary' : 'hover:bg-muted')}
          onClick={() => setWrapPref(!wrap)}
          title="Wrap long lines"
        >
          <WrapText className="w-3.5 h-3.5" />
        </button>
        <button className="h-6 px-1.5 rounded flex items-center gap-1 hover:bg-muted cursor-pointer" onClick={() => void navigator.clipboard?.writeText(text)} title="Copy all">
          <Copy className="w-3.5 h-3.5" />
        </button>
      </div>
      <div ref={scrollRef} className="flex-1 min-h-0 overflow-auto selectable">
        <pre className={cn('px-4 py-3 text-[12px] leading-[1.55] font-mono text-foreground', wrap ? 'whitespace-pre-wrap break-words' : 'whitespace-pre w-max min-w-full')}>
          {lines.map((line, i) => {
            const heading = i + 1 < lines.length && isRule(lines[i + 1]) && line.trim() !== ''
            const rule = isRule(line)
            let body: ReactNode = line || ' '
            if (q && line.toLowerCase().includes(q)) body = marked(line, q, i === current)
            return (
              <Fragment key={i}>
                <span data-line={i} className={cn('block', heading && 'tok-head', rule && 'text-border select-none', i === current && 'bg-accent')}>
                  {body}
                </span>
              </Fragment>
            )
          })}
        </pre>
      </div>
    </div>
  )
}

function marked(line: string, q: string, current: boolean): ReactNode {
  const out: ReactNode[] = []
  const lower = line.toLowerCase()
  let at = 0
  for (;;) {
    const i = lower.indexOf(q, at)
    if (i < 0) break
    if (i > at) out.push(line.slice(at, i))
    out.push(
      <mark key={i} className={cn('rounded-sm', current ? 'bg-primary text-white' : 'bg-warn-soft text-foreground')}>
        {line.slice(i, i + q.length)}
      </mark>,
    )
    at = i + q.length
  }
  out.push(line.slice(at))
  return out
}
