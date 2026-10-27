// The letters of ETERNAL SILVER, drawn for the pixel grid in the manner of the LUNAR lettering:
// heavy stems, thin hairlines, flat bracketed serifs, beaked arms, a kicked leg on the R.
// Every glyph is built for one size from whole-pixel measures (P), never scaled.
//
// P: h cap height · T thick stem · t thin stem · a arm (horizontal stroke) · so serif overhang ·
//    st serif thickness · br the bracket's rows, nearest the serif first · D, d thick and thin
//    diagonals, measured across · bk beak height.
import { Mask, inPoly } from "./lib.mjs";

const PAD = 24;
/** a glyph: `draw(mask)` returns its advance (the width of its body) */
function glyph(draw) {
  const m = new Mask(160, 140, PAD, PAD);
  const adv = draw(m);
  return { m, adv };
}

/** the rows of a bracket in a corner at (x, y): reaching dx-wards, stacked dy-wards */
function fillet(m, x, y, dx, dy, br) {
  br.forEach((n, i) => {
    const ya = dy > 0 ? y + i : y - i - 1;
    m.rect(dx > 0 ? x : x - n, ya, dx > 0 ? x + n : x, ya + 1);
  });
}
function topSerif(m, x0, x1, P, left, right) {
  m.rect(x0 - (left ? P.so : 0), 0, x1 + (right ? P.so : 0), P.st);
  if (left) fillet(m, x0, P.st, -1, 1, P.br);
  if (right) fillet(m, x1, P.st, 1, 1, P.br);
}
function footSerif(m, x0, x1, h, P, left, right) {
  m.rect(x0 - (left ? P.so : 0), h - P.st, x1 + (right ? P.so : 0), h);
  if (left) fillet(m, x0, h - P.st, -1, -1, P.br);
  if (right) fillet(m, x1, h - P.st, 1, -1, P.br);
}
/** an arm's beak at its right end (xr), hanging from y (dir 1) or rising from y (dir -1) */
function beakR(m, xr, y, dir, P) {
  const run = P.bk / 2;
  m.poly([[xr - run - 2, y], [xr - 2, y + dir * P.bk], [xr, y + dir * P.bk], [xr, y]]);
}
function beakL(m, xl, y, dir, P) {
  const run = P.bk / 2;
  m.poly([[xl + run + 2, y], [xl + 2, y + dir * P.bk], [xl, y + dir * P.bk], [xl, y]]);
}

export const I = (P) =>
  glyph((m) => {
    const x0 = P.so;
    const x1 = x0 + P.T;
    m.rect(x0, 0, x1, P.h);
    topSerif(m, x0, x1, P, true, true);
    footSerif(m, x0, x1, P.h, P, true, true);
    return x1 + P.so;
  });

export const L = (P, o = {}) =>
  glyph((m) => {
    const { h, a } = P;
    const x0 = P.so;
    const x1 = x0 + P.T;
    const W = x1 + (o.arm ?? Math.round(h * 0.42));
    m.rect(x0, 0, x1, h);
    topSerif(m, x0, x1, P, true, true);
    footSerif(m, x0, x1, h, P, true, false);
    m.rect(x1, h - a, W, h);
    beakR(m, W, h - a, -1, P);
    fillet(m, x1, h - a, 1, -1, P.br);
    return W;
  });

export const E = (P, o = {}) =>
  glyph((m) => {
    const { h, a } = P;
    const x0 = P.so;
    const x1 = x0 + P.T;
    const arm = o.arm ?? Math.round(h * 0.4);
    const Wt = x1 + arm;
    const Wb = Wt + (o.foot ?? 2);
    const am = Math.max(4, a - 1);
    const yt = Math.round(h * 0.47) - Math.floor(am / 2);
    const Wm = x1 + Math.round(arm * 0.62);
    m.rect(x0, 0, x1, h);
    topSerif(m, x0, x1, P, true, false);
    footSerif(m, x0, x1, h, P, true, false);
    m.rect(x1, 0, Wt, a);
    beakR(m, Wt, a, 1, P);
    fillet(m, x1, a, 1, 1, P.br);
    m.rect(x1, h - a, Wb, h);
    beakR(m, Wb, h - a, -1, P);
    fillet(m, x1, h - a, 1, -1, P.br);
    // the middle arm, and the tick that ends it
    m.rect(x1, yt, Wm, yt + am);
    const tk = Math.max(2, Math.round(P.bk * 0.45));
    m.poly([[Wm - 3, yt], [Wm - 1, yt - tk], [Wm, yt - tk], [Wm, yt + am + tk], [Wm - 1, yt + am + tk], [Wm - 3, yt + am]]);
    return Wb;
  });

export const T = (P, o = {}) =>
  glyph((m) => {
    const { h, a } = P;
    let W = o.w ?? Math.round(h * 0.92);
    if ((W - P.T) % 2) W++;
    const xs = (W - P.T) / 2;
    m.rect(0, 0, W, a);
    beakL(m, 0, a, 1, P);
    beakR(m, W, a, 1, P);
    m.rect(xs, 0, xs + P.T, h);
    fillet(m, xs, a, -1, 1, P.br);
    fillet(m, xs + P.T, a, 1, 1, P.br);
    footSerif(m, xs, xs + P.T, h, P, true, true);
    return W;
  });

export const N = (P, o = {}) =>
  glyph((m) => {
    const { h, so, t, D } = P;
    const run = o.run ?? Math.round(h / 2);
    const W = 2 * so + D + run;
    m.rect(so, 0, so + t, h);
    m.rect(W - so - t, 0, W - so, h);
    m.poly([[so, 0], [so + D, 0], [W - so, h], [W - so - D, h]]);
    m.rect(0, 0, so + 2, P.st);
    fillet(m, so, P.st, -1, 1, P.br);
    footSerif(m, so, so + t, h, P, true, true);
    topSerif(m, W - so - t, W - so, P, true, true);
    return W;
  });

export const A = (P, o = {}) =>
  glyph((m) => {
    const { h, so, D, d, st } = P;
    const r = o.run ?? Math.round(h / 3);
    const ap = o.ap ?? d + 2;
    const xa0 = r + so;
    const xa1 = xa0 + ap;
    const W = xa1 + r + so;
    const outer = [[xa0, 0], [xa1, 0], [xa1 + r, h], [xa0 - r, h]];
    m.poly(outer);
    const ys = ((d + D - ap) * h) / (2 * r);
    m.poly([[xa0 + d - (r / h) * ys, ys], [xa1 + r - D, h], [xa0 - r + d, h]], 0);
    const yc = Math.round(h * (o.bar ?? 0.64));
    const inOuter = inPoly(outer);
    const bar = Math.max(4, P.a - 1);
    m.paint((x, y) => y > yc && y < yc + bar && inOuter(x, y));
    m.rect(xa0 - r - so, h - st, xa0 - r + d + so, h);
    m.rect(xa1 + r - D - so, h - st, xa1 + r + so, h);
    // the apex's little flag to the left
    m.rect(xa0 - 2, 0, xa0, 2);
    return W;
  });

export const V = (P, o = {}) =>
  glyph((m) => {
    const { h, so, D, d, st } = P;
    const r = o.run ?? Math.round(h * 0.4);
    const bw = o.bw ?? 3;
    const W = 2 * so + 2 * r + bw;
    m.poly([[so, 0], [W - so, 0], [so + r + bw, h], [so + r, h]]);
    const ys = h * (1 - (d + D - bw) / (2 * r));
    m.poly([[so + D, 0], [W - so - d, 0], [so + D + (r / h) * ys, ys]], 0);
    m.rect(0, 0, 2 * so + D, st);
    m.rect(W - 2 * so - d, 0, W, st);
    return W;
  });

export const R = (P, o = {}) =>
  glyph((m) => {
    const { h, a, so } = P;
    const x0 = so;
    const x1 = x0 + P.T;
    const yb = o.yb ?? Math.round(h * 0.54);
    const cxb = x1 + (o.flat ?? Math.round(h * 0.12));
    const Rx = o.rx ?? Math.round(yb * 0.62);
    const Tb = P.T - 1;
    m.rect(x0, 0, x1, h);
    topSerif(m, x0, x1, P, true, false);
    footSerif(m, x0, x1, h, P, true, true);
    // the bowl: a block and half an ellipse, less the same again, smaller
    m.rect(x1, 0, cxb, yb);
    m.paint((x, y) => x >= cxb && ((x - cxb) / Rx) ** 2 + ((y - yb / 2) / (yb / 2)) ** 2 <= 1);
    m.rect(x1, a, cxb, yb - a, 0);
    m.paint((x, y) => x >= cxb && ((x - cxb) / (Rx - Tb)) ** 2 + ((y - yb / 2) / (yb / 2 - a)) ** 2 <= 1, 0);
    // the leg, kicked out, a little heavier than a stem and flaring as it goes. With a `drop` it is a
    // swash: it runs on below the baseline, in a foot whose toe turns up — as far as x = `tip`, if given.
    const ye = h + (o.drop ?? 0);
    const xj = x1 + (o.xj ?? 2);
    const Dl = P.D + 1;
    const fl = o.flare ?? 2;
    const toe = o.toe ?? so;
    const xe = o.tip === undefined ? Math.round(xj + (ye - (yb - a)) * (o.slope ?? 0.62)) : o.tip - toe - Dl - fl;
    m.poly([[xj, yb - a], [xj + Dl, yb - a], [xe + Dl + fl, ye], [xe, ye]]);
    const xt = xe + Dl + fl + toe;
    m.rect(xe + Dl + fl - 3, ye - P.st, xt, ye);
    const swash = (o.drop ?? 0) > 0;
    if (swash) m.poly([[xt - 5, ye - P.st], [xt - 1, ye - P.st - 4], [xt, ye - P.st - 4], [xt, ye - P.st]]);
    return swash ? cxb + Rx : Math.max(cxb + Rx, xt);
  });

const smooth = (f) => f * f * (3 - 2 * f);
/** a value along keyed angles: keys [[angle, value], …] with rising or falling angles */
function keyed(keys, ang) {
  for (let i = 0; i + 1 < keys.length; i++) {
    const [a0, v0] = keys[i];
    const [a1, v1] = keys[i + 1];
    if ((ang - a0) * (ang - a1) <= 0) return v0 + (v1 - v0) * smooth((ang - a0) / (a1 - a0));
  }
  return keys[keys.length - 1][1];
}

export const S = (P, o = {}) =>
  glyph((m) => {
    const H = P.h;
    const thin = P.a;
    const thick = P.T;
    const side = o.side ?? Math.round(thick * 0.82);
    const w = o.w ?? Math.round(H * 0.7);
    const yJ = H * (o.waist ?? 0.485);
    const cx = w / 2;
    // the spine: an ellipse over an ellipse, meeting at the waist
    const up = { cy: (thin / 2 + yJ) / 2, ry: (yJ - thin / 2) / 2, rx: (w - side) / 2 - (o.narrow ?? 1.5) };
    const lo = { cy: (yJ + H - thin / 2) / 2, ry: (H - thin / 2 - yJ) / 2, rx: (w - side) / 2 };
    const deg = Math.PI / 180;
    const pts = [];
    const t0 = o.t0 ?? 28;
    const upKeys = [[t0, thin + 1], [90, thin], [180, side], [270, thick]];
    for (let ang = t0; ang <= 270; ang += 0.5) pts.push([cx + up.rx * Math.cos(ang * deg), up.cy - up.ry * Math.sin(ang * deg), keyed(upKeys, ang)]);
    const t1 = o.t1 ?? -152;
    const loKeys = [[90, thick], [0, side], [-90, thin], [t1, thin + 1]];
    for (let ang = 90; ang >= t1; ang -= 0.5) pts.push([cx + lo.rx * Math.cos(ang * deg), lo.cy - lo.ry * Math.sin(ang * deg), keyed(loKeys, ang)]);
    m.stroke(pts);
    // the beaks: a wedge hanging from the upper end, one rising from the lower
    const bk = o.bk ?? P.bk + 2;
    const [ux, uy] = pts[0];
    const xr = Math.round(ux + (thin + 1) / 2);
    const ut = Math.round(uy - (thin + 1) / 2) - 1;
    m.poly([[xr - 3 - bk / 2, ut], [xr, ut - 1], [xr, ut + bk], [xr - 2, ut + bk]]);
    const [lx, ly] = pts[pts.length - 1];
    const xl = Math.round(lx - (thin + 1) / 2);
    const lb = Math.round(ly + (thin + 1) / 2) + 1;
    m.poly([[xl + 3 + bk / 2, lb], [xl, lb + 1], [xl, lb - bk], [xl + 2, lb - bk]]);
    return w;
  });
