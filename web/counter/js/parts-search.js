/**
 * Parts search. Owner: parts-UI agent. Used by ./screens/invoice.js only.
 *
 * Typo-tolerant, instant, over a handful of rows (a manual carries 10-30 parts), so it
 * runs straight over an array on every keystroke — no worker, no debounce needed.
 *
 *   const rows = index(manual);            // [{ part, group, tokens, text }]
 *   const hits = search(rows, "oli");      // same shape, ranked; "" gives rows back
 *
 * A row is searched over the part name, the spec verbatim, the OEM number and the titles
 * (and chapter) of every section of the manual that names that part — so "brake linings"
 * finds the pad material the spec calls "Brake pad material, front".
 */

const DIACRITIC = /\p{M}/gu;
/** Same ceiling search.js keeps, held here so this file stays dependency-free. */
const MAX_QUERY_TOKENS = 12;

/** "Brake fluid DOT 5.1" -> "brake fluid dot 5 1" */
export function fold(value) {
  return String(value == null ? "" : value)
    .toLowerCase()
    .normalize("NFD")
    .replace(DIACRITIC, "")
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function words(value) {
  const text = fold(value);
  return text ? text.split(" ") : [];
}

/** Manuals shout their chapters ("18 SERVICE WORK ON THE ENGINE"); tiles want a label. */
export function chapterLabel(chapter) {
  const raw = String(chapter == null ? "" : chapter)
    .replace(/^\s*\d+(?:\.\d+)*\s+/, "")
    .trim();
  if (!raw) return "";
  if (/[a-z]/.test(raw)) return raw;
  const low = raw.toLowerCase();
  return low.charAt(0).toUpperCase() + low.slice(1);
}

/**
 * Damerau-Levenshtein (adjacent transposition counts as one), capped: returns `cap + 1`
 * the moment a whole row is over the cap, so a long word never costs a full matrix.
 * Transpositions matter here because "oli" for "oil" and "spakr" for "spark" are the
 * typos a thumb actually makes, and plain Levenshtein charges two for them.
 */
export function distance(a, b, cap = 2) {
  if (a === b) return 0;
  if (Math.abs(a.length - b.length) > cap) return cap + 1;
  if (!a.length) return b.length;
  if (!b.length) return a.length;
  let two = null; // the row before last, for the transposition step
  let prev = Array.from({ length: b.length + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i++) {
    const row = new Array(b.length + 1);
    row[0] = i;
    let best = i;
    const ca = a.charCodeAt(i - 1);
    for (let j = 1; j <= b.length; j++) {
      const cost = ca === b.charCodeAt(j - 1) ? 0 : 1;
      let v = Math.min(prev[j] + 1, row[j - 1] + 1, prev[j - 1] + cost);
      if (two && j > 1 && ca === b.charCodeAt(j - 2) && a.charCodeAt(i - 2) === b.charCodeAt(j - 1)) {
        v = Math.min(v, two[j - 2] + 1);
      }
      row[j] = v;
      if (v < best) best = v;
    }
    if (best > cap) return cap + 1;
    two = prev;
    prev = row;
  }
  return prev[b.length];
}

/** One typo from three letters up, two once the word is long enough to hide one. */
function budget(token) {
  if (token.length <= 2) return 0;
  if (token.length <= 6) return 1;
  return 2;
}

/**
 * Build the searchable rows for one mapped manual (ttm.js `manual()` shape).
 * `group` is the chapter most of the referencing sections sit in, so the grid can stack
 * the parts under the heading of the manual that actually talks about them.
 */
export function index(made) {
  const parts = (made && Array.isArray(made.parts) ? made.parts : []).filter(Boolean);
  const sections = made && Array.isArray(made.sections) ? made.sections : [];

  const refs = new Map(); // partId -> { titles: [], chapters: Map<chapter, count> }
  for (const section of sections) {
    const ids = Array.isArray(section.partIds) ? section.partIds : [];
    for (const id of ids) {
      let row = refs.get(id);
      if (!row) {
        row = { titles: [], chapters: new Map() };
        refs.set(id, row);
      }
      if (section.title) row.titles.push(String(section.title));
      const chapter = String(section.chapter || "");
      row.chapters.set(chapter, (row.chapters.get(chapter) || 0) + 1);
    }
  }

  return parts.map((part, order) => {
    const ref = refs.get(part.id);
    let chapter = "";
    if (ref) {
      let best = -1;
      for (const [name, count] of ref.chapters) {
        if (count > best) {
          best = count;
          chapter = name;
        }
      }
    }
    const titles = ref ? ref.titles : [];
    const name = fold(part.name);
    const rest = [part.spec, part.oem, chapter, ...titles].map(fold).filter(Boolean).join(" ");
    const tokens = new Set(words(`${name} ${rest}`));
    return {
      part,
      order,
      group: chapterLabel(chapter),
      titles,
      name,
      nameTokens: words(name),
      text: `${name} ${rest}`.trim(),
      tokens: [...tokens],
    };
  });
}

/** The nine shelves /parts/catalog sorts a vehicle into, in the order the grid stacks them. */
export const GROUPS = [
  ["engine", "Engine"],
  ["drivetrain", "Drivetrain"],
  ["brakes", "Brakes"],
  ["suspension", "Suspension"],
  ["wheels", "Wheels"],
  ["electrics", "Electrics"],
  ["controls", "Controls"],
  ["body", "Body"],
  ["consumables", "Consumables"],
];

const GROUP_LABEL = new Map(GROUPS);

export function groupLabel(id) {
  return GROUP_LABEL.get(String(id || "")) || "";
}

/**
 * Rows for the /parts/catalog answer (ttm.js `partCatalog()` shape): the whole vehicle,
 * not only what the manual prints. Searched over the name, the spec, the OEM number, the
 * group, the backend's synonyms and the part id, so "pads" finds "Brake pad set" and
 * "brakes" finds the shelf.
 */
export function indexCatalog(parts) {
  const list = (Array.isArray(parts) ? parts : []).filter(Boolean);
  return list.map((part, order) => {
    const label = groupLabel(part.group);
    const name = fold(part.name);
    const extras = [part.spec, part.oem, part.group, label, part.id, ...(part.synonyms || [])];
    const rest = extras.map(fold).filter(Boolean).join(" ");
    const tokens = new Set(words(`${name} ${rest}`));
    return {
      part,
      order,
      group: label,
      groupId: part.group || "",
      titles: [],
      name,
      nameTokens: words(name),
      text: `${name} ${rest}`.trim(),
      tokens: [...tokens],
    };
  });
}

/** True when `token` starts a word of `text`, not just sits inside one ("oli" in "cooling"). */
function wordAt(text, token) {
  let i = text.indexOf(token);
  while (i >= 0) {
    if (i === 0 || text.charCodeAt(i - 1) === 32) return true;
    i = text.indexOf(token, i + 1);
  }
  return false;
}

/**
 * How well one row answers one query word; 0 means it does not. The part's own name
 * outranks everything the sections say about it, so a typo in the name ("oli") still
 * beats an exact substring buried in a chapter heading ("cooling").
 */
function scoreToken(row, token) {
  const cap = budget(token);
  let best = 0;

  if (row.name.includes(token)) best = wordAt(row.name, token) ? 9 : 6;
  for (const word of row.nameTokens) {
    if (word === token) best = Math.max(best, 9);
    else if (word.startsWith(token)) best = Math.max(best, 8);
    else if (cap) {
      const d = distance(token, word, cap);
      if (d <= cap) best = Math.max(best, 7 - d * 1.2);
    }
  }
  if (best) return best;

  if (wordAt(row.text, token)) best = 4;
  else if (token.length >= 4 && row.text.includes(token)) best = 2;
  for (const word of row.tokens) {
    if (word.startsWith(token)) best = Math.max(best, 3.4);
    else if (cap) {
      const d = distance(token, word, cap);
      if (d <= cap) best = Math.max(best, 3 - d * 0.7);
    }
  }
  return best;
}

/**
 * Rank `rows` (from index()) against a raw query. Every query word has to land somewhere
 * — exactly, as a prefix, or within one or two typos — so "oil brake" narrows instead of
 * widening. An empty query gives the rows back in manual order.
 */
export function search(rows, query) {
  const list = Array.isArray(rows) ? rows : [];
  // Same ceiling as search.js and pick-search.js (pass 1, BUG-08): every extra word is
  // another Damerau pass over every token of every row, and past a dozen words a query
  // cannot narrow any further. A pasted paragraph is not a search.
  const q = words(query).slice(0, MAX_QUERY_TOKENS);
  if (!q.length) return list.slice();
  const out = [];
  for (const row of list) {
    let total = 0;
    let ok = true;
    for (const token of q) {
      const hit = scoreToken(row, token);
      if (!hit) {
        ok = false;
        break;
      }
      total += hit;
    }
    if (ok) out.push({ row, total });
  }
  out.sort((a, z) => z.total - a.total || a.row.order - z.row.order);
  return out.map((hit) => hit.row);
}
