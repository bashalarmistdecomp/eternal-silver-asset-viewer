// Pixel masks, shapes on them, and a PNG writer — for the Eternal Silver logo.
import { writeFileSync } from "node:fs";
import { crc32, deflateSync } from "node:zlib";

/** A grid of 0/1 with an origin: shape coordinates are the glyph's, (0, 0) at its top left. */
export class Mask {
  constructor(w, h, ox = 0, oy = 0) {
    this.w = w;
    this.h = h;
    this.ox = ox;
    this.oy = oy;
    this.d = new Uint8Array(w * h);
  }
  get(x, y) {
    const X = x + this.ox;
    const Y = y + this.oy;
    return X >= 0 && Y >= 0 && X < this.w && Y < this.h ? this.d[Y * this.w + X] : 0;
  }
  set(x, y, v = 1) {
    const X = x + this.ox;
    const Y = y + this.oy;
    if (X >= 0 && Y >= 0 && X < this.w && Y < this.h) this.d[Y * this.w + X] = v;
  }
  /** every pixel whose centre passes `test(x, y)` becomes v */
  paint(test, v = 1) {
    for (let Y = 0; Y < this.h; Y++)
      for (let X = 0; X < this.w; X++) if (test(X - this.ox + 0.5, Y - this.oy + 0.5)) this.d[Y * this.w + X] = v;
    return this;
  }
  rect(x0, y0, x1, y1, v = 1) {
    return this.paint((x, y) => x > x0 && x < x1 && y > y0 && y < y1, v);
  }
  poly(points, v = 1) {
    return this.paint(inPoly(points), v);
  }
  /** the union of discs along a path: points [x, y, diameter] */
  stroke(points, v = 1) {
    for (const [cx, cy, dia] of points) {
      const r = dia / 2;
      const r2 = r * r;
      for (let Y = Math.floor(cy - r) - 1; Y <= Math.ceil(cy + r) + 1; Y++)
        for (let X = Math.floor(cx - r) - 1; X <= Math.ceil(cx + r) + 1; X++) {
          const dx = X + 0.5 - cx;
          const dy = Y + 0.5 - cy;
          if (dx * dx + dy * dy <= r2) this.set(X, Y, v);
        }
    }
    return this;
  }
  /** [x0, y0, x1, y1] of the set pixels, in glyph coordinates, x1 and y1 exclusive */
  bbox() {
    let x0 = Infinity;
    let y0 = Infinity;
    let x1 = -Infinity;
    let y1 = -Infinity;
    for (let Y = 0; Y < this.h; Y++)
      for (let X = 0; X < this.w; X++)
        if (this.d[Y * this.w + X]) {
          x0 = Math.min(x0, X);
          y0 = Math.min(y0, Y);
          x1 = Math.max(x1, X + 1);
          y1 = Math.max(y1, Y + 1);
        }
    return [x0 - this.ox, y0 - this.oy, x1 - this.ox, y1 - this.oy];
  }
}

/** a point-in-polygon test (even-odd) for a list of [x, y] */
export function inPoly(points) {
  return (x, y) => {
    let inside = false;
    for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
      const [xi, yi] = points[i];
      const [xj, yj] = points[j];
      if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
  };
}

function chunk(type, data) {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type, "latin1"), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body) >>> 0);
  return Buffer.concat([len, body, crc]);
}

/** an RGBA image (a Uint8Array of w * h * 4) as a PNG file */
export function writePng(path, w, h, rgba) {
  const raw = Buffer.alloc((w * 4 + 1) * h);
  for (let y = 0; y < h; y++) Buffer.from(rgba.buffer, rgba.byteOffset + y * w * 4, w * 4).copy(raw, y * (w * 4 + 1) + 1);
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(w, 0);
  ihdr.writeUInt32BE(h, 4);
  ihdr[8] = 8;
  ihdr[9] = 6;
  writeFileSync(
    path,
    Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), chunk("IHDR", ihdr), chunk("IDAT", deflateSync(raw, { level: 9 })), chunk("IEND", Buffer.alloc(0))]),
  );
}

/** "#rrggbb" or "#rrggbbaa" as [r, g, b, a] */
export function rgba(hex) {
  const n = hex.slice(1);
  return [parseInt(n.slice(0, 2), 16), parseInt(n.slice(2, 4), 16), parseInt(n.slice(4, 6), 16), n.length > 6 ? parseInt(n.slice(6, 8), 16) : 255];
}

/** An RGBA picture to draw into. */
export class Picture {
  constructor(w, h) {
    this.w = w;
    this.h = h;
    this.d = new Uint8Array(w * h * 4);
  }
  put(x, y, hex) {
    if (x < 0 || y < 0 || x >= this.w || y >= this.h) return;
    this.d.set(rgba(hex), (y * this.w + x) * 4);
  }
  /** this picture enlarged by a whole number, each pixel a square */
  scaled(k) {
    const out = new Picture(this.w * k, this.h * k);
    for (let y = 0; y < out.h; y++)
      for (let x = 0; x < out.w; x++) {
        const s = (Math.floor(y / k) * this.w + Math.floor(x / k)) * 4;
        out.d.set(this.d.subarray(s, s + 4), (y * out.w + x) * 4);
      }
    return out;
  }
  save(path) {
    writePng(path, this.w, this.h, this.d);
  }
}
