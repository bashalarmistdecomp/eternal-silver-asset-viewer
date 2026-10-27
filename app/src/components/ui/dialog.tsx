import { X } from 'lucide-react'
import { useEffect, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { cn } from '../../lib/utils'

/** A modal dialog: backdrop click and Esc close it. */
export function Dialog({
  title,
  onClose,
  children,
  className,
}: {
  title: string
  onClose: () => void
  children: ReactNode
  className?: string
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onMouseDown={onClose}>
      <div
        className={cn('relative bg-card border border-border rounded-lg shadow-xl max-h-[80vh] flex flex-col w-[480px]', className)}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="px-4 py-3 border-b border-border flex items-center justify-between">
          <h2 className="text-sm font-semibold">{title}</h2>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground cursor-pointer" title="Close">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="p-4 overflow-auto">{children}</div>
      </div>
    </div>,
    document.body,
  )
}
