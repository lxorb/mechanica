/**
 * Rewrites the generic-model table in web/store/models/CREDITS.md from the source.json files
 * models-fetch.mjs leaves next to each model.glb. Owner: vehicle-models agent.
 *
 *   node web/tools/credits-generic.mjs
 *
 * Attribution is a licence obligation, not a nicety, so it is generated from what is actually on
 * disk rather than typed — a model that ships without a credit line is a licence breach, and a
 * credit line for a model that no longer ships is a lie. Only the block between the two
 * GENERIC-TABLE markers is touched.
 */

import { existsSync, readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const GENERIC = resolve(HERE, "..", "store", "models", "generic");
const CREDITS = resolve(HERE, "..", "store", "models", "CREDITS.md");
const START = "<!-- GENERIC-TABLE-START — written by web/tools/credits-generic.mjs, do not hand-edit -->";
const END = "<!-- GENERIC-TABLE-END -->";

const LICENSES = {
  cc0: ["CC0 1.0", "https://creativecommons.org/publicdomain/zero/1.0/"],
  by: ["CC BY 4.0", "https://creativecommons.org/licenses/by/4.0/"],
  "by-sa": ["CC BY-SA 4.0", "https://creativecommons.org/licenses/by-sa/4.0/"],
  "by-nc": ["CC BY-NC 4.0", "https://creativecommons.org/licenses/by-nc/4.0/"],
  "by-nc-sa": ["CC BY-NC-SA 4.0", "https://creativecommons.org/licenses/by-nc-sa/4.0/"],
};

const mb = (bytes) => `${(bytes / 1024 / 1024).toFixed(2)} MB`;

function main() {
  if (!existsSync(GENERIC)) { console.log("no generic models yet"); return; }
  const rows = [];
  for (const name of readdirSync(GENERIC).sort()) {
    const dir = join(GENERIC, name);
    const meta = join(dir, "source.json");
    const glb = join(dir, "model.glb");
    if (!statSync(dir).isDirectory() || !existsSync(meta) || !existsSync(glb)) continue;
    const row = JSON.parse(readFileSync(meta, "utf8"));
    rows.push({ ...row, name, bytes: statSync(glb).size, hasLicense: existsSync(join(dir, "license.txt")) });
  }
  if (!rows.length) { console.log("no generic models on disk"); return; }

  const table = [
    "| type | model | author | licence | size | tris |",
    "| --- | --- | --- | --- | --- | --- |",
    ...rows.map((r) => {
      const [label, url] = LICENSES[r.license] || [r.license || "?", ""];
      return `| \`generic/${r.name}\` | [${r.title}](${r.url}) | [${r.author}](${r.authorUrl}) | ${url ? `[${label}](${url})` : label} | ${mb(r.bytes)} | ${(r.triangles || 0).toLocaleString()} |`;
    }),
    "",
    "Credit lines to reproduce wherever these are shown:",
    "",
    ...rows.map((r) => {
      const [label] = LICENSES[r.license] || [r.license || "?"];
      return r.license === "cc0"
        ? `> "${r.title}" by ${r.author} is CC0 — no attribution required, credited anyway.`
        : `> This work is based on "${r.title}" by ${r.author}, licensed under ${label}.`;
    }),
  ];

  const missing = rows.filter((r) => !r.hasLicense).map((r) => r.name);
  if (missing.length) {
    table.push("", `_No \`license.txt\` came in the archive for: ${missing.join(", ")} — the licence above is what the Sketchfab API reported._`);
  }
  const nc = rows.filter((r) => String(r.license).includes("nc"));
  if (nc.length) {
    table.push("", `**${nc.length} of these are NC (non-commercial):** ${nc.map((r) => r.name).join(", ")}. Fine for the demo, swap before anything is sold.`);
  }

  const text = readFileSync(CREDITS, "utf8");
  const a = text.indexOf(START);
  const b = text.indexOf(END);
  if (a < 0 || b < 0) { console.error(`markers missing in ${CREDITS}`); process.exit(1); }
  writeFileSync(CREDITS, `${text.slice(0, a + START.length)}\n\n${table.join("\n")}\n\n${text.slice(b)}`);
  console.log(`${rows.length} generic models credited in ${CREDITS}`);
  console.log(`total ${mb(rows.reduce((s, r) => s + r.bytes, 0))}`);
}

main();
