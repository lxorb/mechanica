/**
 * Contrast gate for the themes. Owner: theme agent.
 *
 *   node web/tools/theme-contrast.mjs            # table + exit 1 if a required pair fails
 *   node web/tools/theme-contrast.mjs --md       # the same table as Markdown, for docs/ui-themes.md
 *
 * Reads the token values straight out of css/counter.css (:root = Workshop) and css/themes.css,
 * so the numbers can never drift from the stylesheets. Only flat colours are resolved: a token
 * whose value is a gradient is skipped, and `var(--x)` is followed one hop.
 *
 * Every pair below is text over a ground the app actually puts it on. WCAG AA is 4.5:1 for body
 * text; pairs marked large (>= 24 px, or >= 19 px bold) are held to 3:1, which is the same
 * standard applied to the uppercase display type this app sets its headings in.
 */

import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const CSS = resolve(HERE, "..", "counter", "css");

/** [text token, ground token, where it shows, large?] */
const PAIRS = [
  ["--fg", "--bg", "body text on the ground", false],
  ["--fg", "--card", "row and card text", false],
  ["--muted", "--card", "labels, specs, placeholders", false],
  ["--muted", "--bg", "meta on the ground", false],
  ["--muted-2", "--card", "years, spans", false],
  ["--faint", "--card", "placeholder and ghost art", true],
  ["--slab-fg", "--slab", "the reader bar, primary button", false],
  ["--accent-ink", "--accent", "MECHANICA on the ticket bar", false],
  ["--accent-2-ink", "--accent-2", "every .btn label", false],
  ["--ok-ink", "--ok", "a year whose manual is ready", false],
  ["--danger-ink", "--danger", "the 3D retry stamp", false],
  ["--accent", "--card", "chapter numbers, shop names", true],
  ["--accent-2", "--slab", "the page count on the MANUAL button", true],
  ["--line", "--bg", "the 3 px rule on the ground", true],
  ["--line", "--card", "the 3 px rule on a card", true],
  ["--page-ink", "--page", "the manual itself", false],
];

const THEMES = ["workshop", "night", "blueprint", "track", "paper"];

function blocks() {
  const root = readFileSync(join(CSS, "counter.css"), "utf8");
  const alt = readFileSync(join(CSS, "themes.css"), "utf8");
  const out = { workshop: grab(root, /:root\s*\{([\s\S]*?)\n\}/) };
  for (const id of THEMES.slice(1)) {
    out[id] = { ...out.workshop, ...grab(alt, new RegExp(`\\[data-theme="${id}"\\]\\s*\\{([\\s\\S]*?)\\n\\}`)) };
  }
  return out;
}

function grab(src, re) {
  const body = (src.match(re) || [, ""])[1];
  const map = {};
  for (const line of body.split("\n")) {
    const m = line.match(/^\s*(--[a-z0-9-]+)\s*:\s*([^;]+);/i);
    if (m) map[m[1]] = m[2].trim();
  }
  return map;
}

function rgb(value, map, depth = 0) {
  if (!value || depth > 4) return null;
  const v = value.trim();
  const ref = v.match(/^var\((--[a-z0-9-]+)/i);
  if (ref) return rgb(map[ref[1]], map, depth + 1);
  let m = v.match(/^#([0-9a-f]{3})$/i);
  if (m) return [...m[1]].map((c) => parseInt(c + c, 16));
  m = v.match(/^#([0-9a-f]{6})$/i);
  if (m) return [0, 2, 4].map((i) => parseInt(m[1].slice(i, i + 2), 16));
  m = v.match(/^rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)/i);
  if (m) return [Number(m[1]), Number(m[2]), Number(m[3])];
  return null;
}

const lin = (c) => (c / 255 <= 0.03928 ? c / 255 / 12.92 : ((c / 255 + 0.055) / 1.055) ** 2.4);
const lum = ([r, g, b]) => 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);

function ratio(a, b) {
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}

const md = process.argv.includes("--md");
const maps = blocks();
const rows = [];
let fails = 0;

for (const [text, ground, where, large] of PAIRS) {
  const need = large ? 3 : 4.5;
  const cells = THEMES.map((id) => {
    const a = rgb(maps[id][text], maps[id]);
    const b = rgb(maps[id][ground], maps[id]);
    if (!a || !b) return { id, n: null };
    const n = ratio(a, b);
    // Workshop is the shipped look and is held fixed by the brief; its misses are reported,
    // not enforced, so that the four new themes can still be gated hard.
    if (n < need && id !== "workshop") fails += 1;
    return { id, n, bad: n < need };
  });
  rows.push({ text, ground, where, need, cells });
}

if (md) {
  console.log(`| text on ground | need | ${THEMES.join(" | ")} |`);
  console.log(`| --- | --- | ${THEMES.map(() => "---").join(" | ")} |`);
  for (const r of rows) {
    const cells = r.cells.map((c) => (c.n == null ? "—" : `${c.n.toFixed(2)}${c.bad ? " ⚠" : ""}`));
    console.log(`| \`${r.text}\` on \`${r.ground}\` — ${r.where} | ${r.need} | ${cells.join(" | ")} |`);
  }
} else {
  console.log(`${"pair".padEnd(34)}${"need".padEnd(6)}${THEMES.map((t) => t.padEnd(11)).join("")}`);
  for (const r of rows) {
    const label = `${r.text} on ${r.ground}`;
    const cells = r.cells.map((c) => `${c.n == null ? "—" : c.n.toFixed(2)}${c.bad ? " !!" : "   "}`.padEnd(11));
    console.log(`${label.padEnd(34)}${String(r.need).padEnd(6)}${cells.join("")}`);
  }
  console.log(fails ? `\n${fails} failing pair(s) outside Workshop` : "\nevery non-Workshop pair passes");
}
process.exitCode = fails ? 1 : 0;
