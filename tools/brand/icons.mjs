// The app's icon files, all from the one 64 x 64 picture: whole multiples of it each pixel a square, the sizes
// between and below it averaged over the area each pixel covers; and icon.ico and icon.icns, which hold PNGs.
import { writeFileSync } from "node:fs";
import { crc32, deflateSync } from "node:zlib";
import { Picture } from "./lib.mjs";

const ICONS = "app/src-tauri/icons";
/** file -> size: the set Tauri's `tauri icon` writes for a desktop app */
const FILES = {
  "32x32.png": 32,
  "64x64.png": 64,
  "128x128.png": 128,
  "128x128@2x.png": 256,
  "icon.png": 512,
  "Square30x30Logo.png": 30,
  "Square44x44Logo.png": 44,
  "Square71x71Logo.png": 71,
  "Square89x89Logo.png": 89,
  "Square107x107Logo.png": 107,
  "Square142x142Logo.png": 142,
  "Square150x150Logo.png": 150,
  "Square284x284Logo.png": 284,
  "Square310x310Logo.png": 310,
  "StoreLogo.png": 50,
};
const ICO = [16, 24, 32, 48, 64, 256];
/** icns types holding a PNG, and their sizes */
const ICNS = [["ic07", 128], ["ic08", 256], ["ic09", 512], ["ic10", 1024], ["ic11", 32], ["ic12", 64], ["ic13", 256], ["ic14", 512]];

/** the picture at `size` pixels square */
export function sized(pic, size) {
  if (size % pic.w === 0) return pic.scaled(size / pic.w);
  return area(pic, size);
}

/** each new pixel the average of the old ones it covers, by how much of each it covers (alpha weighted) */
function area(pic, size) {
  const out = new Picture(size, size);
  const k = pic.w / size;
  const span = (i) => {
    const a = i * k;
    const b = a + k;
    const cells = [];
    for (let s = Math.floor(a); s < Math.min(pic.w, Math.ceil(b)); s++) cells.push([s, Math.min(b, s + 1) - Math.max(a, s)]);
    return cells;
  };
  for (let y = 0; y < size; y++)
    for (let x = 0; x < size; x++) {
      let r = 0, g = 0, b = 0, a = 0, cover = 0;
      for (const [sy, wy] of span(y))
        for (const [sx, wx] of span(x)) {
          const w = wx * wy;
          const i = (sy * pic.w + sx) * 4;
          const al = pic.d[i + 3] * w;
          r += pic.d[i] * al;
          g += pic.d[i + 1] * al;
          b += pic.d[i + 2] * al;
          a += al;
          cover += w;
        }
      const o = (y * size + x) * 4;
      if (a > 0) out.d.set([Math.round(r / a), Math.round(g / a), Math.round(b / a), Math.round(a / cover)], o);
    }
  return out;
}

/** a picture as the bytes of a PNG file (lib.mjs's writer, kept as bytes) */
export function png(pic) {
  const chunk = (type, data) => {
    const len = Buffer.alloc(4);
    len.writeUInt32BE(data.length);
    const body = Buffer.concat([Buffer.from(type, "latin1"), data]);
    const crc = Buffer.alloc(4);
    crc.writeUInt32BE(crc32(body) >>> 0);
    return Buffer.concat([len, body, crc]);
  };
  const { w, h, d } = pic;
  const raw = Buffer.alloc((w * 4 + 1) * h);
  for (let y = 0; y < h; y++) Buffer.from(d.buffer, d.byteOffset + y * w * 4, w * 4).copy(raw, y * (w * 4 + 1) + 1);
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(w, 0);
  ihdr.writeUInt32BE(h, 4);
  ihdr[8] = 8;
  ihdr[9] = 6;
  return Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), chunk("IHDR", ihdr), chunk("IDAT", deflateSync(raw, { level: 9 })), chunk("IEND", Buffer.alloc(0))]);
}

/** an .ico of PNGs: its header, a row a picture, the pictures */
function ico(pngs) {
  const head = Buffer.alloc(6 + 16 * pngs.length);
  head.writeUInt16LE(0, 0);
  head.writeUInt16LE(1, 2);
  head.writeUInt16LE(pngs.length, 4);
  let at = head.length;
  pngs.forEach(([size, bytes], i) => {
    const e = 6 + 16 * i;
    head[e] = size >= 256 ? 0 : size;
    head[e + 1] = size >= 256 ? 0 : size;
    head.writeUInt16LE(1, e + 4);
    head.writeUInt16LE(32, e + 6);
    head.writeUInt32LE(bytes.length, e + 8);
    head.writeUInt32LE(at, e + 12);
    at += bytes.length;
  });
  return Buffer.concat([head, ...pngs.map(([, bytes]) => bytes)]);
}

/** an .icns of PNGs: each a type, its length and the PNG */
function icns(entries) {
  const parts = entries.map(([type, bytes]) => {
    const h = Buffer.alloc(8);
    h.write(type, 0, "latin1");
    h.writeUInt32BE(bytes.length + 8, 4);
    return Buffer.concat([h, bytes]);
  });
  const head = Buffer.alloc(8);
  head.write("icns", 0, "latin1");
  head.writeUInt32BE(8 + parts.reduce((n, p) => n + p.length, 0), 4);
  return Buffer.concat([head, ...parts]);
}

/** every icon file the app's build reads, written through `out` (a path in the repository -> where to write it) */
export function writeIcons(pic, out) {
  for (const [file, size] of Object.entries(FILES)) writeFileSync(out(`${ICONS}/${file}`), png(sized(pic, size)));
  writeFileSync(out(`${ICONS}/icon.ico`), ico(ICO.map((s) => [s, png(sized(pic, s))])));
  writeFileSync(out(`${ICONS}/icon.icns`), icns(ICNS.map(([type, s]) => [type, png(sized(pic, s))])));
}
