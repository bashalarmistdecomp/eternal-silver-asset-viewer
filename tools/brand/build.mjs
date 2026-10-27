// The Asset Viewer's logo and icon: Eternal Silver's logo with ASSET VIEWER in gold under it, and ES over AV on a
// night tile. The logo's letters are glyphs.mjs's and the gold capitals gold.mjs's; this sets them, colours them,
// gives them the dark edge and the indigo rim, and writes the pictures where the app and the README read them.
// Usage: node tools/brand/build.mjs [a folder]   — with a folder named, everything is written there instead.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { Picture } from "./lib.mjs";
import * as G from "./glyphs.mjs";
import * as Gold from "./gold.mjs";
import { writeIcons } from "./icons.mjs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const into = process.argv[2];
const out = (path) => {
  const p = into ? join(into, path.replace(/\//g, "_")) : join(ROOT, path);
  mkdirSync(dirname(p), { recursive: true });
  return p;
};

/** the whole-pixel measures of a letter h pixels tall (glyphs.mjs says what each is) */
const measures = (h) => ({
  h,
  T: Math.round(h * 0.25),
  t: Math.max(4, Math.round(h * 0.12)),
  a: Math.max(4, Math.round(h * 0.125)),
  so: 3,
  st: h >= 34 ? 3 : 2,
  br: [2, 1],
  D: Math.round(h * 0.25),
  d: Math.max(4, Math.round(h * 0.12)),
  bk: 2 * Math.round(h * 0.1),
});

// ---- the colours ---------------------------------------------------------------------------------
/** rows of colour from bands [hex, rows, "hard" | "edge"?]: a band's last row is checkered into the next, unless the next is hard or it is an edge */
function ramp(bands) {
  const rows = [];
  bands.forEach(([hex, n, kind], i) => {
    for (let k = 0; k < n; k++) rows.push({ a: hex });
    const next = bands[i + 1];
    if (next !== undefined && next[2] !== "hard" && kind !== "edge" && n >= 2) rows[rows.length - 1].b = next[0];
  });
  return rows;
}
/** `rows` rows shared out among the colours, the first ones getting what is left over */
function spread(colours, rows) {
  const base = Math.floor(rows / colours.length);
  let extra = rows - base * colours.length;
  return colours.map((c) => [c, base + (extra-- > 0 ? 1 : 0)]);
}
/** chrome for a letter h tall: sky down to a white horizon, a dark line, and up again; `tail` colours whatever drops below the baseline */
function chrome(c, h, drop = 0) {
  const horizon = Math.round(h * 0.52);
  const bands = [...spread(c.top, horizon - 2), [c.shine, 2, "edge"], [c.horizon, 2, "hard"], ...spread(c.bottom, h - horizon - 2)];
  if (drop > 0) bands.push(...spread(c.tail, drop));
  return ramp(bands.filter(([, n]) => n > 0));
}
// ETERNAL: the blue of Eternal Silver's planet
const BLUE = {
  top: ["#1f50c0", "#2c68dc", "#4585ee", "#6aa4f8", "#98c4fc", "#c8e2fe"],
  shine: "#ffffff",
  horizon: "#0c1a5e",
  bottom: ["#1a3aa0", "#2c5cd0", "#4a84ea", "#7fb2f8", "#b9d9fe"],
  tail: ["#b9d9fe"],
};
// SILVER: the silver of its moon
const SILVER = {
  top: ["#5b6c98", "#7889b2", "#98a8ca", "#b8c5df", "#d8e0f0"],
  shine: "#ffffff",
  horizon: "#141c48",
  bottom: ["#343f6c", "#505d8c", "#7483ac", "#9dabc9", "#c5cfe4", "#e6ebf5"],
  tail: ["#ffffff", "#c5cfe4"],
};
// the name under the logo: Eternal Silver's title gold — pale at the top, deep at the foot, a step at the middle;
// a colour a row, no horizon, so the small letters stay whole
const GOLD = [[0, "#fff2b4"], [0.45, "#f0b52a"], [0.55, "#d98d10"], [1, "#8c5a0c"]];
function gold(h) {
  const hex = (c) => [1, 3, 5].map((i) => parseInt(c.slice(i, i + 2), 16));
  const rows = [];
  for (let y = 0; y < h; y++) {
    const t = (y + 0.5) / h;
    const i = GOLD.findIndex(([t1], k) => k > 0 && t <= t1);
    const [t0, c0] = GOLD[i - 1];
    const [t1, c1] = GOLD[i];
    const [a, b] = [hex(c0), hex(c1)];
    const f = (t - t0) / (t1 - t0);
    rows.push({ a: "#" + a.map((v, k) => Math.round(v + (b[k] - v) * f).toString(16).padStart(2, "0")).join("") });
  }
  return rows;
}
const KEY = "#ffffff";
const OUTLINE = "#060818";
// the outermost line: the indigo of Eternal Silver's icon's border — lighter than a night sky, darker than paper
const RIM = "#3a4398";
// the icon's night, and its stars
const NIGHT = "#10133c";
const STAR = ["#ffffff", "#c9d3ff", "#7e8be0"];

// ---- the words -----------------------------------------------------------------------------------
const advance = (glyphs) => glyphs.reduce((x, [g, space]) => x + space + g.adv, 0);
/** ETERNAL at one height: [glyph, space before it] */
function eternal(h) {
  const P = measures(h);
  // the R inside the word keeps its leg close, so the N can stand near it; the kick is for the R that ends SILVER
  return [[G.E(P), 0], [G.T(P), 2], [G.E(P), 2], [G.R(P, { toe: 2, slope: 0.42 }), 2], [G.N(P), 1], [G.A(P), 1], [G.L(P), 1]];
}
/** SILVER at one height, up to its R; the R's leg is a swash dropping `drop` below the baseline */
function silver(h, drop) {
  const P = measures(h);
  const before = [[G.S(P, { t0: 20, t1: -158, w: Math.round(h * 0.74) }), 0], [G.I(P), 3], [G.L(P), 3], [G.V(P), -Math.round(h / 8)], [G.E(P), 1]];
  return [...before, [G.R(P, { drop, flare: 3, slope: 0.66 }), 3]];
}
/** how far right a line's ink reaches, from its left */
function reach(glyphs) {
  let x = 0;
  let right = 0;
  for (const [g, space] of glyphs) {
    x += space;
    right = Math.max(right, x + g.m.bbox()[2]);
    x += g.adv;
  }
  return right;
}

// ---- drawing lettering ---------------------------------------------------------------------------
const MARGIN = 10;
/** the most pixels of what is behind the logo the rim may cut off and fill: the S's lower curve holds 9 to 30, the V's
 *  open notch 130 and more */
const SPECK = 64;
/** what of a w by h grid a flood from its border reaches, through the cells `through(i)` lets it */
function fromBorder(w, h, through) {
  const reached = new Uint8Array(w * h);
  const queue = [];
  const visit = (x, y) => {
    if (x < 0 || y < 0 || x >= w || y >= h || reached[y * w + x] || !through(y * w + x)) return;
    reached[y * w + x] = 1;
    queue.push([x, y]);
  };
  for (let x = 0; x < w; x++) { visit(x, 0); visit(x, h - 1); }
  for (let y = 0; y < h; y++) { visit(0, y); visit(w - 1, y); }
  while (queue.length > 0) { const [x, y] = queue.pop(); visit(x + 1, y); visit(x - 1, y); visit(x, y + 1); visit(x, y - 1); }
  return reached;
}
/** the pixels of a letter's mask its own ink closes off: [X, Y] in the mask's grid, what the mask's border cannot reach */
function holes(m) {
  const reached = fromBorder(m.w, m.h, (i) => !m.d[i]);
  const out = [];
  for (let Y = 0; Y < m.h; Y++) for (let X = 0; X < m.w; X++) if (!m.d[Y * m.w + X] && !reached[Y * m.w + X]) out.push([X, Y]);
  return out;
}
/**
 * Lines of letters, coloured, with the dark edge and the rim, trimmed to a pixel of air. A line is { glyphs, x, y,
 * rows, key }: its colour a row, and where the white key goes — every edge pixel ("edge", the chrome's), or only
 * the top of a stroke in the letter's upper half ("top", the gold's). `glint` is the logo's letter height, for
 * its three glints; none without it.
 */
function lettering(name, lines, glintH) {
  const W = Math.max(...lines.map((l) => l.x + reach(l.glyphs))) + 2 * MARGIN + 6;
  const H = Math.max(...lines.map((l) => l.y + l.rows.length)) + 2 * MARGIN + 2;
  const letters = new Uint8Array(W * H);
  const lineOf = new Uint8Array(W * H);
  lines.forEach((line, n) => {
    let x = MARGIN + line.x;
    for (const [g, space] of line.glyphs) {
      x += space;
      const { m } = g;
      for (let Y = 0; Y < m.h; Y++)
        for (let X = 0; X < m.w; X++) {
          if (!m.d[Y * m.w + X]) continue;
          const px = x + X - m.ox;
          const py = MARGIN + line.y + Y - m.oy;
          if (px < 0 || py < 0 || px >= W || py >= H) throw new Error(`${name}: a letter of line ${n + 1} leaves the canvas at ${px}, ${py}`);
          letters[py * W + px] = 1;
          lineOf[py * W + px] = n + 1;
        }
      x += g.adv;
    }
  });
  const at = (x, y) => (x >= 0 && y >= 0 && x < W && y < H ? letters[y * W + x] : 0);

  // the dark edge: the letters grown two pixels, round-cornered — and heavier to the lower right, as the
  // LUNAR lettering's is: the same shape again, stepped down and across
  const edge = new Uint8Array(W * H);
  for (let y = 0; y < H; y++)
    for (let x = 0; x < W; x++) {
      if (!letters[y * W + x]) continue;
      for (let dy = -2; dy <= 2; dy++)
        for (let dx = -2; dx <= 2; dx++) {
          if (dx * dx + dy * dy > 4) continue;
          if (x + dx >= 0 && y + dy >= 0 && x + dx < W && y + dy < H) edge[(y + dy) * W + x + dx] = 1;
        }
    }
  const dark = new Uint8Array(edge);
  for (let k = 1; k <= 2; k++) for (let y = k; y < H; y++) for (let x = k; x < W; x++) if (edge[(y - k) * W + x - k]) dark[y * W + x] = 1;

  // a letter's own holes — the bowl of an R, the A's triangle — are dark, as its edge is; whatever else the
  // letters' edges close off, a slot between two letters or the gap between the lines, is left clear, the rim
  // drawn round it as round the outside (Eternal Silver's logo, the owner, 2026-10-26)
  lines.forEach((line) => {
    let x = MARGIN + line.x;
    for (const [g, space] of line.glyphs) {
      x += space;
      for (const [X, Y] of holes(g.m)) dark[(MARGIN + line.y + Y - g.m.oy) * W + x + X - g.m.ox] = 1;
      x += g.adv;
    }
  });

  const pic = new Picture(W, H);
  const rim = new Uint8Array(W * H);
  for (let y = 0; y < H; y++)
    for (let x = 0; x < W; x++) {
      const i = y * W + x;
      if (letters[i]) {
        const line = lines[lineOf[i] - 1];
        const ly = y - MARGIN - line.y;
        const row = line.rows[ly];
        if (row === undefined) throw new Error(`${name}: line ${lineOf[i]} has no colour for its row ${ly}`);
        const key = line.key === "top" ? !at(x, y - 1) && ly < line.rows.length / 2 : !at(x - 1, y) || !at(x + 1, y) || !at(x, y - 1) || !at(x, y + 1);
        pic.put(x, y, key ? KEY : row.b !== undefined && (x + y) % 2 === 0 ? row.b : row.a);
      } else if (dark[i]) pic.put(x, y, OUTLINE);
      else if ([[1, 0], [-1, 0], [0, 1], [0, -1]].some(([dx, dy]) => dark[(y + dy) * W + x + dx])) {
        pic.put(x, y, RIM);
        rim[i] = 1;
      }
    }

  // a speck of what is behind the logo that the rim alone cuts off — the outside reaching it through a crack the
  // rim fills, as the S's lower curve holds one — is the rim's colour too (the owner, 2026-10-26); a pocket the dark
  // closes off, a slot between letters, stays clear, and so does an opening bigger than a speck, the V's notch
  const clear = (i) => !letters[i] && !dark[i];
  const see = (i) => clear(i) && !rim[i];
  const open = fromBorder(W, H, clear);
  const sea = fromBorder(W, H, see);
  const done = new Uint8Array(W * H);
  for (let start = 0; start < W * H; start++) {
    if (!see(start) || sea[start] || done[start]) continue;
    const speck = [start];
    done[start] = 1;
    for (let n = 0; n < speck.length; n++) {
      const i = speck[n];
      for (const j of [i % W > 0 ? i - 1 : -1, i % W < W - 1 ? i + 1 : -1, i - W, i + W])
        if (j >= 0 && j < W * H && see(j) && !done[j]) {
          done[j] = 1;
          speck.push(j);
        }
    }
    if (open[start] && speck.length <= SPECK) for (const i of speck) pic.put(i % W, Math.floor(i / W), RIM);
  }

  // the glints: four-pointed, as Eternal Silver's stars are — on the E's corner, the S's shoulder and the swash's toe
  if (glintH) {
    const [first, second] = lines;
    const shoulder = Math.round(glintH * 0.19);
    glint(pic, MARGIN + first.x + 2, MARGIN + first.y + 2, 5);
    glint(pic, MARGIN + second.x + shoulder, MARGIN + second.y + shoulder, 3);
    glint(pic, MARGIN + second.x + reach(second.glyphs) - 1, MARGIN + second.y + second.rows.length - 9, 4);
  }
  return trim(pic);
}

/** a four-pointed glint at (cx, cy), its arms n long */
function glint(pic, cx, cy, n) {
  const tone = (k) => (k <= Math.ceil(n / 3) ? "#ffffff" : k <= Math.ceil((2 * n) / 3) ? "#cfe0ff" : "#86a6f6");
  for (let k = n; k >= 1; k--) for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) pic.put(cx + dx * k, cy + dy * k, tone(k));
  if (n >= 4) for (const [dx, dy] of [[1, 1], [-1, 1], [1, -1], [-1, -1]]) pic.put(cx + dx, cy + dy, "#e6efff");
  pic.put(cx, cy, "#ffffff");
}

/** the picture cut to what was drawn, a pixel of air around it */
function trim(pic) {
  const { w: W, h: H } = pic;
  let x0 = W, y0 = H, x1 = 0, y1 = 0;
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) if (pic.d[(y * W + x) * 4 + 3]) { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); }
  const cut = new Picture(x1 - x0 + 3, y1 - y0 + 3);
  for (let y = 0; y < cut.h; y++)
    for (let x = 0; x < cut.w; x++) {
      const sx = x + x0 - 1;
      const sy = y + y0 - 1;
      if (sx >= 0 && sy >= 0 && sx < W && sy < H) cut.d.set(pic.d.subarray((sy * W + sx) * 4, (sy * W + sx) * 4 + 4), (y * cut.w + x) * 4);
    }
  return cut;
}

/** `top` drawn over `pic` at (x, y), where it is not clear */
function over(pic, top, x, y) {
  for (let Y = 0; Y < top.h; Y++)
    for (let X = 0; X < top.w; X++) {
      const s = (Y * top.w + X) * 4;
      if (top.d[s + 3]) pic.d.set(top.d.subarray(s, s + 4), ((y + Y) * pic.w + x + X) * 4);
    }
}

// ---- the logo ------------------------------------------------------------------------------------
const GAP = 4;
/** Eternal Silver's logo at its title-screen size (letters 30 pixels tall), and the name in gold under it — set
 * below the swash's drop, so the swash ends on it */
function logo() {
  const h = 30;
  const drop = 8;
  const top = eternal(h);
  const bottom = silver(h, drop);
  const name = Gold.words("ASSET VIEWER");
  const width = advance(top);
  return lettering(
    "logo",
    [
      { glyphs: top, x: 0, y: 0, rows: chrome(BLUE, h) },
      { glyphs: bottom, x: Math.floor((width - reach(bottom)) / 2), y: h + GAP, rows: chrome(SILVER, h, drop) },
      { glyphs: name, x: Math.floor((width - reach(name)) / 2), y: 2 * (h + GAP) + drop, rows: gold(Gold.HEIGHT), key: "top" },
    ],
    h,
  );
}

// ---- the icon ------------------------------------------------------------------------------------
/** ES over AV on a night tile, 64 pixels square: the E blue as ETERNAL's, the S silver as SILVER's, AV gold */
function icon() {
  const size = 64;
  const h = 22;
  const P = measures(h);
  const E = [[G.E(P), 0]];
  const S = [[G.S(P, { t0: 20, t1: -158, w: Math.round(h * 0.74) }), 0]];
  const sx = advance(E) + 2;
  const av = Gold.words("AV", { track: 2 });
  const top = sx + reach(S);
  const words = lettering(
    "icon",
    [
      { glyphs: E, x: Math.floor((reach(av) - top) / 2), y: 0, rows: chrome(BLUE, h) },
      { glyphs: S, x: Math.floor((reach(av) - top) / 2) + sx, y: 0, rows: chrome(SILVER, h) },
      { glyphs: av, x: 0, y: h + GAP, rows: gold(Gold.HEIGHT), key: "top" },
    ],
    0,
  );
  const pic = tile(size);
  over(pic, words, Math.floor((size - words.w) / 2), Math.floor((size - words.h) / 2));
  return pic;
}

/** the tile: Eternal Silver's icon's rounded square — the indigo border, the night inside, a few stars */
function tile(size) {
  const pic = new Picture(size, size);
  const r = Math.round(size * 0.19);
  const inside = (x, y, inset) => {
    const lo = inset + r;
    const hi = size - 1 - inset - r;
    const cx = Math.min(Math.max(x, lo), hi);
    const cy = Math.min(Math.max(y, lo), hi);
    return (x - cx) ** 2 + (y - cy) ** 2 <= (r + 0.5) ** 2 && x >= inset && y >= inset && x < size - inset && y < size - inset;
  };
  const border = Math.max(1, Math.round(size / 32));
  for (let y = 0; y < size; y++)
    for (let x = 0; x < size; x++) {
      if (!inside(x, y, 0)) continue;
      if (!inside(x, y, border)) pic.put(x, y, RIM);
      else pic.put(x, y, NIGHT);
    }
  for (const [x, y, n] of [[8, 8, 2], [56, 9, 1], [7, 56, 1], [56, 55, 2]]) {
    const cx = Math.round((x * size) / 64);
    const cy = Math.round((y * size) / 64);
    for (let k = n; k >= 1; k--) for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) pic.put(cx + dx * k, cy + dy * k, STAR[Math.min(2, k)]);
    pic.put(cx, cy, STAR[0]);
  }
  return pic;
}

// ---- writing them --------------------------------------------------------------------------------
const lockup = logo();
lockup.save(out("app/src/brand/asset-viewer-logo.png"));
lockup.scaled(4).save(out("docs/img/logo.png"));
console.log(`the logo: ${lockup.w} x ${lockup.h}`);

const big = icon();
big.save(out("app/src/brand/asset-viewer-icon.png"));
big.save(out("app/public/favicon.png"));
writeIcons(big, out);
console.log(`the icon: ${big.w} x ${big.h}`);
