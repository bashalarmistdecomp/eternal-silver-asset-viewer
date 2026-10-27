import { cn } from '../../lib/utils'

/** A summary: the providers' {title, fields} — a disc file, an STR's details, a sample's tone. */
export function SummaryView({ title, fields, className }: { title: string; fields: [string, string][]; className?: string }) {
  return (
    <div className={cn('rounded-lg border border-border bg-card shadow-sm p-4 selectable', className)}>
      {title && <h3 className="text-sm font-semibold mb-3 font-mono break-all">{title}</h3>}
      <dl className="grid grid-cols-[minmax(110px,auto)_1fr] gap-x-4 gap-y-1.5 text-xs">
        {fields.map(([k, v], i) => (
          <div key={i} className="contents">
            <dt className="text-muted-foreground">{k}</dt>
            <dd className="font-mono whitespace-pre-wrap break-words">{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}
