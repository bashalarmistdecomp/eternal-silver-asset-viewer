import { Check, TriangleAlert, X } from 'lucide-react'
import { useSyncExternalStore } from 'react'
import { cn } from '../../lib/utils'

export interface Toast {
  id: number
  tone: 'ok' | 'error'
  title: string
  body?: string
  action?: { label: string; run: () => void }
}

let toasts: Toast[] = []
let next = 1
const listeners = new Set<() => void>()
const emit = () => listeners.forEach((l) => l())

export function toast(t: Omit<Toast, 'id'>, ms = 6000) {
  const id = next++
  toasts = [...toasts, { ...t, id }].slice(-4)
  emit()
  if (ms > 0) setTimeout(() => dismiss(id), ms)
}

export function dismiss(id: number) {
  toasts = toasts.filter((t) => t.id !== id)
  emit()
}

export function Toaster() {
  const list = useSyncExternalStore(
    (fn) => {
      listeners.add(fn)
      return () => listeners.delete(fn)
    },
    () => toasts,
  )
  return (
    <div className="fixed bottom-4 right-4 z-[60] flex flex-col gap-2 w-80 pointer-events-none">
      {list.map((t) => (
        <div key={t.id} className="pointer-events-auto rounded-lg border border-border bg-card shadow-lg p-3 flex gap-2.5 animate-fade-in">
          <span className={cn('mt-0.5 shrink-0', t.tone === 'ok' ? 'text-ok' : 'text-destructive')}>
            {t.tone === 'ok' ? <Check className="w-4 h-4" /> : <TriangleAlert className="w-4 h-4" />}
          </span>
          <div className="flex-1 min-w-0">
            <p className="text-xs font-medium">{t.title}</p>
            {t.body && <p className="text-[11px] font-mono text-muted-foreground break-all mt-0.5 selectable">{t.body}</p>}
            {t.action && (
              <button
                className="text-[11px] text-primary hover:underline cursor-pointer mt-1"
                onClick={() => {
                  t.action!.run()
                  dismiss(t.id)
                }}
              >
                {t.action.label}
              </button>
            )}
          </div>
          <button className="text-muted-foreground hover:text-foreground cursor-pointer self-start" onClick={() => dismiss(t.id)} title="Dismiss">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      ))}
    </div>
  )
}
