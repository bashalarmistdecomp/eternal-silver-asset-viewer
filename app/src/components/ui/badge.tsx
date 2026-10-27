import type { ReactNode } from 'react'
import { cn } from '../../lib/utils'

export type Tone = 'ok' | 'warn' | 'info' | 'muted' | 'danger' | 'primary'

const TONES: Record<Tone, string> = {
  ok: 'bg-ok-soft text-ok border-ok/25',
  warn: 'bg-warn-soft text-warn border-warn/30',
  info: 'bg-info-soft text-info border-info/25',
  muted: 'bg-muted text-muted-foreground border-border',
  danger: 'bg-destructive/10 text-destructive border-destructive/30',
  primary: 'bg-accent text-primary border-primary/30',
}

export function Badge({ tone = 'muted', children, className, title }: { tone?: Tone; children: ReactNode; className?: string; title?: string }) {
  return (
    <span
      title={title}
      className={cn('inline-flex items-center gap-1 h-[18px] px-1.5 rounded border text-[10px] font-medium font-mono whitespace-nowrap shrink-0', TONES[tone], className)}
    >
      {children}
    </span>
  )
}
