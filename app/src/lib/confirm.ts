// A question the app asks before doing something the person may not
// want: one at a time, answered in a modal (views/ConfirmHost.tsx), the
// answer handed back as a promise.

import { useSyncExternalStore } from 'react'

export interface Question {
  title: string
  body: string
  ok: string
  cancel: string
}

interface Asking extends Question {
  answer: (yes: boolean) => void
}

let asking: Asking | null = null
const listeners = new Set<() => void>()

function changed() {
  listeners.forEach((l) => l())
}

/** Ask; true when the person goes on. A question asked while another is
 *  open answers the open one "no" first. */
export function confirm(q: Question): Promise<boolean> {
  asking?.answer(false)
  return new Promise((resolve) => {
    const me: Asking = {
      ...q,
      answer: (yes) => {
        if (asking === me) {
          asking = null
          changed()
        }
        resolve(yes)
      },
    }
    asking = me
    changed()
  })
}

/** Whether a question is open: the views' own keys wait while it is. */
export function isAsking(): boolean {
  return asking !== null
}

export function useQuestion(): Asking | null {
  return useSyncExternalStore(
    (fn) => {
      listeners.add(fn)
      return () => listeners.delete(fn)
    },
    () => asking,
  )
}
