import { useCallback, useEffect, useRef, useState } from 'react'

function read<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(`lunar-viewer.${key}`)
    return raw === null ? fallback : (JSON.parse(raw) as T)
  } catch {
    return fallback
  }
}

/**
 * State remembered across launches (a viewer preference: zoom mode, grid,
 * backdrop). A convenience only — storage can be unavailable, and then the
 * value simply resets.
 */
export function useStored<T>(key: string, fallback: T): [T, (v: T | ((old: T) => T)) => void] {
  const [value, setValue] = useState<T>(() => read(key, fallback))
  const set = useCallback(
    (v: T | ((old: T) => T)) => {
      setValue((old) => {
        const next = typeof v === 'function' ? (v as (old: T) => T)(old) : v
        try {
          localStorage.setItem(`lunar-viewer.${key}`, JSON.stringify(next))
        } catch {
          // nothing depends on it
        }
        return next
      })
    },
    [key],
  )
  return [value, set]
}

/** Re-render on animation frames, only when `read()` changes. */
export function useLive(read: () => string): string {
  const [value, setValue] = useState(read)
  const reader = useRef(read)
  useEffect(() => {
    reader.current = read
  })
  useEffect(() => {
    let raf = 0
    let last = ''
    const loop = () => {
      const v = reader.current()
      if (v !== last) {
        last = v
        setValue(v)
      }
      raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(raf)
  }, [])
  return value
}
