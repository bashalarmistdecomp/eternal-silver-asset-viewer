# How the logo and the icon were made

The viewer's logo is Eternal Silver's — the same two words, drawn by the same
code — with ASSET VIEWER in gold under it. Its icon is ES over AV on a night
tile. Both are pictures, and the repository holds the pictures:

- `app/src/brand/asset-viewer-logo.png`: the logo, 216 × 103, its big letters
  30 pixels tall. The Library page shows it at twice that size, each pixel a
  square.
- `docs/img/logo.png`: the same at four times, for the README.
- `app/src/brand/asset-viewer-icon.png` and `app/public/favicon.png`: the
  icon, 64 × 64. The rail at the app's left shows it.
- `app/src-tauri/icons/`: every icon file the desktop build reads, from that
  one picture.

These files are the record of how those pictures were drawn, so they can be
drawn again, or changed:

- `glyphs.mjs`: the nine letters of ETERNAL SILVER, each built for the pixel
  grid from whole-pixel measures: heavy stems, thin hairlines, bracketed
  serifs, beaked arms, a kicked leg on the R. Eternal Silver's, unchanged.
- `lib.mjs`: the pixel masks, the shapes on them, and the PNG writer.
  Eternal Silver's, unchanged.
- `gold.mjs`: the gold capitals of ASSET VIEWER (and AV), drawn a pixel at a
  time at 17 pixels tall: Roman capitals, a three-pixel stem against
  two-pixel hairlines, the thick stroke the one falling to the right. The
  logo's own letters cut down to that size close up and lose their shapes,
  so these are drawn for it.
- `build.mjs`: the words set and spaced; the colours (blue chrome for
  ETERNAL, silver for SILVER, and for the name Eternal Silver's title gold, a
  colour a row from pale to deep with a step at the middle); the dark edge
  round the letters and in their own holes, the slots between them left
  open with the indigo rim drawn round them, as Eternal Silver's logo has
  it since 2026-10-26; the glints; the icon's tile; and where each picture
  is written.
- `icons.mjs`: the icon's sizes (whole multiples of the 64 × 64 picture each
  pixel a square, the rest averaged over the area each pixel covers),
  `icon.ico` and `icon.icns`.

To draw them again: `node tools/brand/build.mjs` from the top of the
repository. It needs nothing but Node, and writes the files above byte for
byte; `node tools/brand/build.mjs <a folder>` writes them there instead, to
compare.

Ours: no pixel of the games' art.
