/* Vickrey specimen plates.
 *
 * Sample plates for the demo walk: labelled illustrations of real species,
 * drawn in the field client's own ink-on-parchment language so the sample walk
 * needs no camera, no network, and no stock photography.
 *
 * These are illustrations, not photographs, and they say so. Each plate is a
 * data URI, so it costs no request and never leaves the device. The species are
 * chosen so the plate and the label always agree -- a wrong-looking photo would
 * be worse than no photo at all.
 *
 * Pure: no DOM, no network. Returns strings, so it runs in tests too.
 */
(function (root, factory) {
  var api = factory(root);
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  if (typeof window !== "undefined" && typeof document !== "undefined") {
    window.VickreySpecimens = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  var W = 360;
  var H = 270;
  var ART = 226; /* the drawing sits above the museum label strip */

  var PARCHMENT = "#f4efe4";
  var INK = "#1c1915";
  var MUTED = "#6d655b";
  var RULE = "#ddd4c4";
  var BERRY = "#a32020";
  var BREAST = "#b8501e";

  function esc(text) {
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  /* The plate frame: parchment, a double rule, a plate number and a museum
   * label. Every plate is captioned with its Latin name, because that is what
   * makes it read as a specimen rather than a decorative icon. */
  function frame(art, number, common, latin) {
    return (
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' +
      W +
      " " +
      H +
      '" width="' +
      W +
      '" height="' +
      H +
      '">' +
      '<rect width="' +
      W +
      '" height="' +
      H +
      '" fill="' +
      PARCHMENT +
      '"/>' +
      '<rect x="9.5" y="9.5" width="' +
      (W - 19) +
      '" height="' +
      (H - 19) +
      '" fill="none" stroke="' +
      RULE +
      '" stroke-width="1.5"/>' +
      '<rect x="13.5" y="13.5" width="' +
      (W - 27) +
      '" height="' +
      (H - 27) +
      '" fill="none" stroke="' +
      RULE +
      '" stroke-width="0.6"/>' +
      art +
      /* the museum label strip */
      '<path d="M22 ' +
      ART +
      "H" +
      (W - 22) +
      '" stroke="' +
      RULE +
      '" stroke-width="1"/>' +
      '<text x="22" y="' +
      (ART + 17) +
      '" font-family="Georgia, \'Times New Roman\', serif" font-size="13.5" fill="' +
      INK +
      '">' +
      esc(common) +
      "</text>" +
      '<text x="22" y="' +
      (ART + 30) +
      '" font-family="Georgia, \'Times New Roman\', serif" font-size="11" font-style="italic" fill="' +
      MUTED +
      '">' +
      esc(latin) +
      "</text>" +
      '<text x="' +
      (W - 22) +
      '" y="' +
      (ART + 24) +
      '" text-anchor="end" font-family="Georgia, serif" font-size="10" letter-spacing="1.5" fill="' +
      MUTED +
      '">PL. ' +
      esc(number) +
      "</text>" +
      "</svg>"
    );
  }

  function dataUri(svg) {
    return "data:image/svg+xml," + encodeURIComponent(svg);
  }

  /* --------------------------------------------------------------- ivy --
   * Hedera helix: a cordate leaf -- heart-shaped base, one pointed central
   * lobe and a pair of lateral lobes, each pair separated by a sinus. Getting
   * the sinuses is what separates ivy from a maple, so they are drawn, not
   * smoothed away. */
  function ivyLeaf(cx, cy, scale, rotate) {
    return (
      '<g transform="translate(' +
      cx +
      " " +
      cy +
      ") rotate(" +
      rotate +
      ") scale(" +
      scale +
      ')">' +
      '<path d="M0 34 C-10 44 -26 46 -34 38 C-26 28 -22 20 -26 10 C-40 14 -50 4 -52 -8 C-40 -6 -34 -12 -32 -20 C-40 -28 -34 -42 -22 -50 C-16 -42 -8 -38 0 -56 C8 -38 16 -42 22 -50 C34 -42 40 -28 32 -20 C34 -12 40 -6 52 -8 C50 4 40 14 26 10 C22 20 26 28 34 38 C26 46 10 44 0 34 Z" fill="' +
      PARCHMENT +
      '" stroke="' +
      INK +
      '" stroke-width="2" stroke-linejoin="round"/>' +
      /* one vein per lobe, radiating from the petiole */
      '<g stroke="' +
      INK +
      '" stroke-width="1" opacity="0.6" fill="none">' +
      '<path d="M0 36 L0 -52"/>' +
      '<path d="M0 36 L48 -6"/>' +
      '<path d="M0 36 L-48 -6"/>' +
      "</g>" +
      "</g>"
    );
  }

  function ivyPlate() {
    var art =
      "<g>" +
      /* a trailing stem, kept inside the plate above the museum label */
      '<path d="M34 196 C76 186 102 162 122 134 C136 114 146 92 152 66" fill="none" stroke="' +
      MUTED +
      '" stroke-width="2.4" stroke-linecap="round"/>' +
      ivyLeaf(152, 62, 0.54, 7) +
      ivyLeaf(124, 128, 0.66, -11) +
      ivyLeaf(70, 178, 0.56, -24) +
      /* the pale growing tip, which is how ivy is identified in the field */
      '<path d="M152 66 C162 50 176 40 194 36" fill="none" stroke="' +
      MUTED +
      '" stroke-width="2.2" stroke-linecap="round"/>' +
      '<path d="M194 36 C200 26 212 20 224 20 C214 26 208 36 206 46 C200 42 196 39 194 36 Z" fill="' +
      PARCHMENT +
      '" stroke="' +
      INK +
      '" stroke-width="1.8" stroke-linejoin="round"/>' +
      "</g>";
    return frame(art, "14", "Common ivy", "Hedera helix");
  }

  /* ---------------------------------------------------------- hawthorn --
   * Crataegus monogyna: deeply lobed leaves (not ivy -- the lobes are rounded
   * and cut nearly to the midrib), a thorn, and a cluster of red haws. */
  function hawthornLeaf(cx, cy, scale, rotate) {
    return (
      '<g transform="translate(' +
      cx +
      " " +
      cy +
      ") rotate(" +
      rotate +
      ") scale(" +
      scale +
      ')">' +
      '<path d="M0 -56 C12 -34 18 -30 30 -32 C26 -18 28 -12 44 -14 C34 -2 38 4 52 4 C40 12 40 18 50 28 C36 28 32 34 36 46 C24 38 16 40 12 52 C8 40 2 34 0 26 C-2 34 -8 40 -12 52 C-16 40 -24 38 -36 46 C-32 34 -40 28 -50 28 C-40 18 -40 12 -52 4 C-38 4 -34 -2 -44 -14 C-28 -12 -26 -18 -30 -32 C-18 -30 -12 -34 0 -56 Z" fill="' +
      PARCHMENT +
      '" stroke="' +
      INK +
      '" stroke-width="2" stroke-linejoin="round"/>' +
      '<g stroke="' +
      INK +
      '" stroke-width="1" opacity="0.6" fill="none">' +
      '<path d="M0 50 L0 -52"/>' +
      '<path d="M0 50 L47 26"/>' +
      '<path d="M0 50 L-47 26"/>' +
      '<path d="M0 50 L49 3"/>' +
      '<path d="M0 50 L-49 3"/>' +
      "</g>" +
      "</g>"
    );
  }

  function haw(cy) {
    return (
      '<g transform="translate(0 ' +
      cy +
      ')">' +
      '<circle cx="-15" cy="0" r="7.5" fill="' +
      BERRY +
      '" stroke="' +
      INK +
      '" stroke-width="1.5"/>' +
      '<circle cx="0" cy="-9" r="8.5" fill="' +
      BERRY +
      '" stroke="' +
      INK +
      '" stroke-width="1.5"/>' +
      '<circle cx="14" cy="1" r="7" fill="' +
      BERRY +
      '" stroke="' +
      INK +
      '" stroke-width="1.5"/>' +
      /* the persistent calyx scar each haw carries at the tip */
      '<circle cx="0" cy="-9" r="2" fill="' +
      PARCHMENT +
      '"/>' +
      "</g>"
    );
  }

  function hawthornPlate() {
    var art =
      "<g>" +
      '<path d="M40 206 C88 198 132 184 170 162 C206 141 232 116 246 86" fill="none" stroke="' +
      MUTED +
      '" stroke-width="2.8" stroke-linecap="round"/>' +
      /* The thorn, on a bare stretch of stem where it can actually be seen.
       * A hawthorn's straight thorn is what separates it from blackthorn. */
      '<path d="M86 197 L120 190 L90 191 Z" fill="' +
      INK +
      '"/>' +
      /* a side shoot, carried up to the cluster of haws */
      '<path d="M226 124 C242 122 254 114 260 102" fill="none" stroke="' +
      MUTED +
      '" stroke-width="1.6" stroke-linecap="round"/>' +
      '<path d="M260 102 C262 90 264 80 270 72" fill="none" stroke="' +
      MUTED +
      '" stroke-width="1.6" stroke-linecap="round"/>' +
      hawthornLeaf(120, 154, 0.72, -16) +
      hawthornLeaf(204, 110, 0.6, 18) +
      '<g transform="translate(270 72)">' +
      haw(0) +
      "</g>" +
      "</g>";
    return frame(art, "27", "Common hawthorn", "Crataegus monogyna");
  }

  /* -------------------------------------------------------------- robin --
   * Erithacus rubecula, in profile on a twig. Drawn as a silhouette with the
   * orange breast left as colour, because that bib is the field mark and a
   * fully rendered bird would not read at journal-thumbnail size. */
  function robinPlate() {
    var art =
      "<g>" +
      /* the twig */
      '<path d="M24 214 C88 208 150 200 214 190 C262 182 300 176 336 170" fill="none" stroke="' +
      MUTED +
      '" stroke-width="3.4" stroke-linecap="round"/>' +
      '<path d="M214 190 C222 176 234 168 248 164" fill="none" stroke="' +
      MUTED +
      '" stroke-width="1.8" stroke-linecap="round"/>' +
      '<g opacity="0.55" fill="' +
      MUTED +
      '">' +
      '<circle cx="252" cy="162" r="4"/>' +
      '<circle cx="266" cy="166" r="3.2"/>' +
      "</g>" +
      /* legs */
      '<g stroke="' +
      INK +
      '" stroke-width="2" stroke-linecap="round">' +
      '<path d="M148 176 L146 200"/>' +
      '<path d="M146 200 L136 204"/>' +
      '<path d="M146 200 L156 204"/>' +
      '<path d="M164 174 L164 200"/>' +
      '<path d="M164 200 L156 204"/>' +
      '<path d="M164 200 L174 204"/>' +
      "</g>" +
      /* Body, head and tail as ONE silhouette, so there is no seam where the
       * tail meets the back. */
      '<path d="M120 63 C144 60 160 73 168 93 C178 114 196 126 218 134 L302 112 L298 143 L214 161 C190 172 160 176 136 170 C112 164 97 148 94 127 C91 101 101 66 120 63 Z" fill="' +
      INK +
      '"/>' +
      /* tail feather line, kept faint so the tail still reads as feathers */
      '<g stroke="' +
      PARCHMENT +
      '" stroke-width="1" opacity="0.28">' +
      '<path d="M214 147 L296 128"/>' +
      "</g>" +
      /* the orange bib */
      '<path d="M115 68 C99 81 93 104 99 127 C105 150 121 164 139 170 C121 151 113 124 116 100 C118 84 117 73 115 68 Z" fill="' +
      BREAST +
      '"/>' +
      /* beak */
      '<path d="M93 86 L62 95 L94 101 Z" fill="' +
      INK +
      '"/>' +
      /* eye, left as a light catchlight the way an engraver would */
      '<circle cx="119" cy="86" r="4.2" fill="' +
      PARCHMENT +
      '"/>' +
      '<circle cx="119" cy="86" r="1.8" fill="' +
      INK +
      '"/>' +
      /* wing edge */
      '<path d="M158 104 C178 116 194 127 206 137" fill="none" stroke="' +
      PARCHMENT +
      '" stroke-width="1.4" opacity="0.32"/>' +
      "</g>";
    return frame(art, "8", "European robin", "Erithucus rubecula");
  }

  var PLATES = {
    ivy: { svg: ivyPlate, species: "Common ivy", kind: "plant" },
    hawthorn: {
      svg: hawthornPlate,
      species: "Common hawthorn",
      kind: "tree",
    },
    robin: { svg: robinPlate, species: "European robin", kind: "bird" },
  };

  /* A plate as a data URI, ready for an <img src>. */
  function plate(name) {
    var entry = PLATES[name];
    if (!entry) {
      throw new Error("no specimen plate named " + name);
    }
    return dataUri(entry.svg());
  }

  function names() {
    return Object.keys(PLATES);
  }

  return {
    ART: ART,
    HEIGHT: H,
    WIDTH: W,
    dataUri: dataUri,
    frame: frame,
    names: names,
    plate: plate,
    plates: PLATES,
  };
});
