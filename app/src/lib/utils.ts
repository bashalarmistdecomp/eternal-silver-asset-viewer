import { clsx, type ClassValue } from 'clsx'
import type { MouseEvent } from 'react'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) seconds = 0
  const m = Math.floor(seconds / 60)
  const s = seconds - m * 60
  return `${m}:${s.toFixed(1).padStart(4, '0')}`
}

export function fmtBytes(n: number): string {
  if (n >= 1 << 30) return `${(n / (1 << 30)).toFixed(2)} GB`
  if (n >= 1 << 20) return `${(n / (1 << 20)).toFixed(1)} MB`
  if (n >= 1 << 10) return `${(n / (1 << 10)).toFixed(0)} KB`
  return `${n} B`
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n.toLocaleString()} ${n === 1 ? one : many}`
}

export function basename(path: string): string {
  return path.split(/[\\/]/).pop() ?? path
}

export function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v))
}

/** A keyboard event that belongs to a text field, not to the app. */
export function inField(e: KeyboardEvent): boolean {
  const t = e.target as HTMLElement | null
  if (!t) return false
  return t.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName)
}

/** A keyboard event the focused control answers itself, not the app: typing
 *  in a field, or Space and Enter pressing a button or following a link. */
export function forControl(e: KeyboardEvent): boolean {
  if (inField(e)) return true
  if (e.key !== ' ' && e.key !== 'Enter') return false
  const t = e.target as HTMLElement | null
  return !!t?.matches?.('button, a[href], [role="button"], [role="link"], summary')
}

/** A tab or a list row chosen with the mouse keeps no focus, so the app's
 *  keys stay the app's after it (Space plays, Enter plays the row
 *  selected); Tab still reaches it, and then it answers them itself. */
export function clickKeepsKeys(e: MouseEvent) {
  e.preventDefault()
  const focused = document.activeElement as HTMLElement | null
  focused?.blur?.()
}

const SHIPPABLE = new Set(['lunadata', 'disc-file', 'exe-image', 'transcribed'])

/** Whether a source kind is one the decoders know (backend/decoders/inventory.py SOURCE_KINDS). */
export function kindTone(kind: string): 'ok' | 'warn' {
  return SHIPPABLE.has(kind) ? 'ok' : 'warn'
}

/** A Mac, whose keyboards name the modifiers ⌘ and ⌥, not Ctrl and Alt. */
export const onMac = typeof navigator !== 'undefined' && /Mac/.test(navigator.platform)

/** A shortcut as this machine's keyboard names it: keyName('Ctrl', 'F') is ⌘F on a Mac. */
export function keyName(mod: 'Ctrl' | 'Alt', key: string): string {
  return onMac ? `${mod === 'Ctrl' ? '⌘' : '⌥'}${key}` : `${mod}+${key}`
}
