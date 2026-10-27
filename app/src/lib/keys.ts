// Space plays and pauses whatever is in front of the user: the movie on
// the stage while one is open, the audio transport otherwise.

let space: (() => void) | null = null

export function claimSpace(fn: () => void): () => void {
  space = fn
  return () => {
    if (space === fn) space = null
  }
}

export function spaceHandler(): (() => void) | null {
  return space
}

let ctx: AudioContext | null = null

/**
 * The one AudioContext movies play through. Resumed on the first user
 * gesture: a webview will not start audio a page merely asked for, and by
 * the time a selection's reply arrives the click that made it may no
 * longer count as one.
 */
export function audioContext(): AudioContext {
  if (!ctx) ctx = new AudioContext()
  return ctx
}

if (typeof window !== 'undefined') {
  // Only until it runs: from then on pausing and playing are the movie's,
  // and a click or key elsewhere must not start a paused one again.
  const unlock = () => {
    void audioContext()
      .resume()
      .then(() => {
        if (ctx?.state !== 'running') return
        window.removeEventListener('pointerdown', unlock, { capture: true })
        window.removeEventListener('keydown', unlock, { capture: true })
      })
  }
  window.addEventListener('pointerdown', unlock, { capture: true })
  window.addEventListener('keydown', unlock, { capture: true })
}
