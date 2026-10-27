import { blobUrl } from './backend'

/** A blob's PNG as an image a canvas may read back. */
export function loadImage(blob: string): Promise<HTMLImageElement> {
  return new Promise((res, rej) => {
    const im = new window.Image()
    // The backend is another origin (127.0.0.1, CORS open); without this the
    // sheets taint any canvas that reads them back for picking.
    im.crossOrigin = 'anonymous'
    im.onload = () => res(im)
    im.onerror = rej
    im.src = blobUrl(blob, 'png')
  })
}

/** An image's pixels, for clicking a sprite by its ink rather than its box. */
export function pixels(im: HTMLImageElement): ImageData | null {
  try {
    const c = document.createElement('canvas')
    c.width = im.width
    c.height = im.height
    const g = c.getContext('2d')!
    g.drawImage(im, 0, 0)
    return g.getImageData(0, 0, im.width, im.height)
  } catch {
    return null // picking falls back to the nearest anchor
  }
}
