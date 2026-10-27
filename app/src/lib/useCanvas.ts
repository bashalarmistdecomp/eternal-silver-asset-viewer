import { useCallback, useEffect, useLayoutEffect, useRef } from 'react'

export type Draw = (ctx: CanvasRenderingContext2D, width: number, height: number) => void

/**
 * A canvas sized to its box at device-pixel resolution, redrawn at most once
 * per frame. `invalidate()` schedules a redraw; resizing does it too.
 */
export function useCanvas(draw: Draw) {
  const ref = useRef<HTMLCanvasElement>(null)
  const drawRef = useRef(draw)
  useLayoutEffect(() => {
    drawRef.current = draw
  })
  const pending = useRef(0)

  const render = useCallback(() => {
    pending.current = 0
    const canvas = ref.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const dpr = window.devicePixelRatio || 1
    const w = canvas.clientWidth
    const h = canvas.clientHeight
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
      canvas.width = Math.round(w * dpr)
      canvas.height = Math.round(h * dpr)
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, w, h)
    drawRef.current(ctx, w, h)
  }, [])

  const invalidate = useCallback(() => {
    if (!pending.current) pending.current = requestAnimationFrame(render)
  }, [render])

  useEffect(() => {
    const canvas = ref.current
    if (!canvas) return
    const ro = new ResizeObserver(() => render())
    ro.observe(canvas)
    return () => {
      ro.disconnect()
      cancelAnimationFrame(pending.current)
      pending.current = 0
    }
  }, [render])

  return { ref, invalidate }
}
