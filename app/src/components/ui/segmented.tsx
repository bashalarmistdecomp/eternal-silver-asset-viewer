import type { ReactNode } from 'react'
import { cn } from '../../lib/utils'

/** Filter chips: one choice of a few, always visible. */
export function Segmented<T extends string | number>({
  value,
  onChange,
  options,
  className,
}: {
  value: T
  onChange: (v: T) => void
  options: { value: T; label: ReactNode; title?: string; disabled?: boolean }[]
  className?: string
}) {
  return (
    <div className={cn('flex flex-wrap gap-1', className)}>
      {options.map((o) => (
        <button
          key={String(o.value)}
          title={o.title}
          disabled={o.disabled}
          onClick={() => onChange(o.value)}
          className={cn(
            'flex-auto h-6 px-2 rounded text-[11px] font-medium border transition-colors cursor-pointer whitespace-nowrap disabled:opacity-40 disabled:cursor-default',
            value === o.value
              ? 'bg-primary text-primary-foreground border-primary'
              : 'bg-background border-border text-muted-foreground hover:text-foreground',
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}
