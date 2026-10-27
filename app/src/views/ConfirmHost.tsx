import { useEffect, useRef } from 'react'
import { Button } from '../components/ui/button'
import { Dialog } from '../components/ui/dialog'
import { useQuestion } from '../lib/confirm'

/** The open question (lib/confirm.ts), if any. Esc and the backdrop say no. */
export function ConfirmHost() {
  const q = useQuestion()
  const ok = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (q) ok.current?.focus()
  }, [q])
  if (!q) return null
  return (
    <Dialog title={q.title} onClose={() => q.answer(false)} className="w-[420px]">
      <p className="text-xs leading-relaxed text-secondary-foreground">{q.body}</p>
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={() => q.answer(false)}>
          {q.cancel}
        </Button>
        <Button ref={ok} size="sm" onClick={() => q.answer(true)}>
          {q.ok}
        </Button>
      </div>
    </Dialog>
  )
}
