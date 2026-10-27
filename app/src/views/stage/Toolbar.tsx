import type { ReactNode } from 'react'
import { cn } from '../../lib/utils'

/** Groups in a row that wraps; the line before a row's first group sits
 *  just outside it, where the clip hides it. */
const GROUPS = '-ml-px flex flex-wrap items-center gap-x-2 gap-y-1'

/**
 * A bar of tools over the stage, in groups: `children` from the left, the
 * `end` groups together on the right. A group keeps together; where the
 * stage is too narrow for them all, what does not fit goes on to another
 * row (the `end` groups still on the right), so nothing is cut off or drawn
 * past the stage. A thin line parts the groups on a row.
 */
export function Toolbar({ children, end }: { children?: ReactNode; end?: ReactNode }) {
  return (
    <div className="shrink-0 overflow-hidden bg-stage-raised border-b border-stage-border text-stage-foreground">
      <div className={cn(GROUPS, 'min-h-10 py-1.5 pr-2')}>
        {children}
        {end && (
          <div className="ml-auto min-w-0 overflow-hidden">
            <div className={GROUPS}>{end}</div>
          </div>
        )}
      </div>
    </div>
  )
}

/** Tools that belong together. `fill`: readouts that take their row's spare
 *  width, right-aligned, and give way first: the first truncates, those that
 *  no longer fit whole are hidden (no line before it). */
export function ToolGroup({ fill, children }: { fill?: boolean; children: ReactNode }) {
  return (
    <div
      className={cn(
        'relative min-w-0 flex flex-wrap items-center gap-1.5',
        fill
          ? 'flex-1 basis-0 h-7 justify-end content-start overflow-hidden *:h-7 *:leading-7'
          : 'pl-2 before:absolute before:left-0 before:top-1 before:bottom-1 before:border-l before:border-stage-border',
      )}
    >
      {children}
    </div>
  )
}
