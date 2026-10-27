import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { cn } from '../../lib/utils'

/** Track an element's scroll position and size. */
function useScrollBox() {
  const ref = useRef<HTMLDivElement>(null)
  const [box, setBox] = useState({ top: 0, height: 600 })
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const update = () => setBox({ top: el.scrollTop, height: el.clientHeight })
    update()
    const ro = new ResizeObserver(update)
    ro.observe(el)
    el.addEventListener('scroll', update, { passive: true })
    return () => {
      ro.disconnect()
      el.removeEventListener('scroll', update)
    }
  }, [])
  return { ref, box }
}

const OVERSCAN = 6

/**
 * Rows of one fixed height; only those on screen (plus a few) are built,
 * so a list of thousands scrolls like a list of ten.
 */
export function VirtualList<T>({
  items,
  rowHeight,
  render,
  className,
  empty,
  scrollTo,
}: {
  items: T[]
  rowHeight: number
  render: (item: T, index: number) => ReactNode
  className?: string
  empty?: ReactNode
  /** Keep this row in view when it changes (e.g. the selection). */
  scrollTo?: number | null
}) {
  const { ref, box } = useScrollBox()
  const first = Math.max(0, Math.floor(box.top / rowHeight) - OVERSCAN)
  const last = Math.min(items.length, Math.ceil((box.top + box.height) / rowHeight) + OVERSCAN)

  useEffect(() => {
    const el = ref.current
    if (!el || scrollTo == null || scrollTo < 0) return
    const y = scrollTo * rowHeight
    if (y < el.scrollTop) el.scrollTop = y
    else if (y + rowHeight > el.scrollTop + el.clientHeight) el.scrollTop = y + rowHeight - el.clientHeight
  }, [ref, scrollTo, rowHeight])

  return (
    <div ref={ref} className={cn('flex-1 overflow-y-auto', className)}>
      {items.length === 0 ? (
        empty
      ) : (
        <div style={{ height: items.length * rowHeight, position: 'relative' }}>
          {items.slice(first, last).map((item, i) => (
            <div key={first + i} style={{ position: 'absolute', top: (first + i) * rowHeight, height: rowHeight, left: 0, right: 0 }}>
              {render(item, first + i)}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
