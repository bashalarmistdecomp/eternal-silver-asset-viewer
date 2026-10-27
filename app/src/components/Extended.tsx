import { ChevronDown, ChevronRight } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { cn } from '../lib/utils'

/**
 * The extended info: how the game does it, the code's names, the hex
 * (docs/taxonomy.md, "The rule"). Folded in Fan mode, open in Advanced; a
 * parent keys it by the mode, so changing mode folds or opens it again.
 */
export function Extended({
  advanced,
  title = 'Extended info',
  className,
  children,
}: {
  advanced: boolean
  title?: string
  className?: string
  children: ReactNode
}) {
  const [open, setOpen] = useState(advanced)
  return (
    <div className={className}>
      <button
        className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground hover:text-foreground cursor-pointer"
        onClick={() => setOpen((o) => !o)}
      >
        {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        {title}
      </button>
      <div className={cn('mt-2', !open && 'hidden')}>{children}</div>
    </div>
  )
}
