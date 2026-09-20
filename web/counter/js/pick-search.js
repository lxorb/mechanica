/**
 * Pick-screen search index. Owner: step-3 agent. Used only by ./screens/pick.js.
 *
 * One flat list of everything the manual can open, built from two sources and deduped:
 *   1. the PDF outline (manual.outline, or manual.toc when the tree is missing) — every
 *      chapter AND subchapter, with depth, the heading verbatim, and a page RANGE worked
 *      out from the next heading that starts a new page;
 *   2. the indexed sections (the jobs from T.jobsFor(bikeId)) — the things the LLM pass
 *      actually cut out of the PDF, with keywords and highlights.
 *
 * Dedupe key is normalised-title + start page, so KTM's outline row
 *   "18.3 Checking the engine oil level"  p.114
 * and its section
 *   "Checking the engine oil level"       pageStart 114
 * become ONE entry that keeps the manual's own heading and gains the section's job,
 * keywords and part ids. An outline row with no section keeps job:null; pick.js
 * synthesises a job from `page`..`pageEnd` for those.
 *
 * search() is instant, prefix-first and typo tolerant (trigram + Damerau-Levenshtein,
 * the same ladder ./search.js uses for bikes). Every query token has to match something,
 * so more typing always narrows. Scoring, best first:
 *   0 exact token · 1 token prefix · 2 substring of the title · 3 substring of the
 *   keywords · 4 trigram >= 0.5 · 5 one or two typos.
 */

import { fold, tokens } from "./search.js";

const TIER_EXACT = 0;
const TIER_PREFIX = 1;
const TIER_TITLE = 2;
const TIER_TEXT = 3;
const TIER_GRAM = 4;
const TIER_TYPO = 5;
const TIER_NONE = 9;

/** A whole chapter can be 60 pages; opening that many PDF sheets is not a job. */
export const MAX_SPAN = 24;

/* ------------------------------------------------------------------ text helpers */

/** "18.3 Checking the engine oil level" -> { number: "18.3", label: "Checking the..." } */
const NUMBER_RE = /^\s*(\d+(?:[.:]\d+)*)[.:)]?\s+(?=\S)/;

export function splitHeading(title) {
  const raw = String(title == null ? "" : title).trim();
  const hit = NUMBER_RE.exec(raw);
  if (!hit) return { number: "", label: raw };
  return { number: hit[1], label: raw.slice(hit[0].length).trim() || raw };
}

/** Dedupe / lookup key: the heading without its numbering, folded hard. */
export function normTitle(title) {
  return fold(splitHeading(title).label);
}

function trigrams(s) {
  const out = new Set();
  for (let i = 0; i + 3 <= s.length; i++) out.add(s.slice(i, i + 3));
  return out;
}

function gramSim(need, haveSet) {
  if (!need.size) return 0;
  let hit = 0;
  for (const g of need) if (haveSet.has(g)) hit++;
  return hit / need.size;
}

/** Damerau-Levenshtein with an early bail once every row is over `max`. */
function damerau(a, b, max) {
  const n = a.length;
  const m = b.length;
  if (Math.abs(n - m) > max) return max + 1;
  if (!n) return m;
  if (!m) return n;
  let prev2 = new Array(m + 1);
  let prev = new Array(m + 1);
  let cur = new Array(m + 1);
  for (let j = 0; j <= m; j++) prev[j] = j;
  for (let i = 1; i <= n; i++) {
    cur[0] = i;
    let best = i;
    for (let j = 1; j <= m; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      let v = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost);
      if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) {
        v = Math.min(v, prev2[j - 2] + 1);
      }
      cur[j] = v;
      if (v < best) best = v;
    }
    if (best > max) return max + 1;
    const spin = prev2;
    prev2 = prev;
    prev = cur;
    cur = spin;
  }
  return prev[m];
}

/* ------------------------------------------------------------------ the index */

function walkOutline(nodes, depth, parent, out) {
  for (const node of nodes || []) {
    if (!node) continue;
    const title = String(node.title == null ? "" : node.title).trim();
    if (!title) continue;
    const kids = Array.isArray(node.children) ? node.children.filter(Boolean) : [];
    const row = {
      title,
      page: Math.max(1, Number(node.page) || 1),
      depth,
      parent,
      hasKids: kids.length > 0,
      index: out.length,
    };
    out.push(row);
    if (kids.length) walkOutline(kids, depth + 1, row, out);
  }
  return out;
}

/** manual.toc is already flat ({title,page,level}); rebuild parent links from the levels. */
function walkToc(toc) {
  const out = [];
  const stack = [];
  for (const node of toc || []) {
    if (!node) continue;
    const title = String(node.title == null ? "" : node.title).trim();
    if (!title) continue;
    const depth = Math.max(0, Number(node.level) || 0);
    while (stack.length > depth) stack.pop();
    const parent = stack.length ? stack[stack.length - 1] : null;
    const row = {
      title,
      page: Math.max(1, Number(node.page) || 1),
      depth,
      parent,
      hasKids: false,
      index: out.length,
    };
    if (parent) parent.hasKids = true;
    out.push(row);
    stack[depth] = row;
    stack.length = depth + 1;
  }
  return out;
}

/**
 * Where each heading stops. A heading with children runs until the next heading at its own
 * level or shallower; a leaf runs until the next heading that starts a later page. Both are
 * clamped to the manual's page count, so "18 SERVICE WORK ON THE ENGINE" really does cover
 * its whole chapter while "18.3 Checking the engine oil level" covers one page.
 */
function closeRanges(rows, pages) {
  const total = Number(pages) || 0;
  const last = total || (rows.length ? rows[rows.length - 1].page : 1);
  for (let i = 0; i < rows.length; i++) {
    const row = rows[i];
    let end = last;
    if (row.hasKids) {
      for (let j = i + 1; j < rows.length; j++) {
        if (rows[j].depth <= row.depth) {
          end = rows[j].page - 1;
          break;
        }
      }
    } else {
      for (let j = i + 1; j < rows.length; j++) {
        if (rows[j].page > row.page) {
          end = rows[j].page - 1;
          break;
        }
      }
    }
    row.pageEnd = Math.max(row.page, Math.min(end, last));
  }
  return rows;
}

function jobPage(job) {
  if (!job) return 1;
  if (Array.isArray(job.pages) && job.pages.length && job.pages[0] != null) return Number(job.pages[0]) || 1;
  if (job.pageStart != null) return Number(job.pageStart) || 1;
  if (job.page != null) return Number(job.page) || 1;
  return 1;
}

function jobEnd(job) {
  if (!job) return 1;
  if (Array.isArray(job.pages) && job.pages.length) return Number(job.pages[job.pages.length - 1]) || jobPage(job);
  if (job.pageEnd != null) return Number(job.pageEnd) || jobPage(job);
  return jobPage(job);
}

function terms(entry) {
  const seen = new Set();
  const push = (value) => {
    for (const t of tokens(value)) if (t.length > 1 || /\d/.test(t)) seen.add(t);
  };
  push(entry.title);
  push(entry.chapter);
  for (const word of entry.keywords) push(word);
  const list = [];
  for (const t of seen) list.push({ t, grams: trigrams(t), len: t.length });
  return list;
}

/**
 * build({ manual, jobs, pages }) -> entries[]
 * Document order, so an empty query can render the contents exactly as the manual prints it.
 */
export function build({ manual, jobs, pages } = {}) {
  const made = manual || {};
  const total = Number(pages || made.pages) || 0;
  const tree = Array.isArray(made.outline) && made.outline.length
    ? walkOutline(made.outline, 0, null, [])
    : walkToc(made.toc);
  closeRanges(tree, total);

  const entries = [];
  const byKey = new Map();

  const add = (entry) => {
    const key = `${normTitle(entry.title)}|${entry.page}`;
    const hit = byKey.get(key);
    if (hit) return hit;
    entry.key = key;
    entry.id = `e${entries.length}`;
    entries.push(entry);
    byKey.set(key, entry);
    return entry;
  };

  const rowToEntry = new Map();
  for (const row of tree) {
    const head = splitHeading(row.title);
    const entry = add({
      title: row.title,
      label: head.label,
      number: head.number,
      page: row.page,
      pageEnd: row.pageEnd,
      depth: row.depth,
      kind: "chapter",
      parentId: null,
      childIds: [],
      chapter: row.parent ? row.parent.title : "",
      keywords: [],
      job: null,
      partIds: [],
      order: entries.length,
    });
    rowToEntry.set(row, entry);
    if (row.parent) {
      const up = rowToEntry.get(row.parent);
      if (up && up !== entry) {
        entry.parentId = up.id;
        up.childIds.push(entry.id);
      }
    }
  }

  for (const job of jobs || []) {
    if (!job || job.synthetic) continue;
    const page = jobPage(job);
    const head = splitHeading(job.title || job.sectionId || "");
    const entry = add({
      title: job.title || job.sectionId || "",
      label: head.label,
      number: head.number,
      page,
      pageEnd: Math.max(page, jobEnd(job)),
      depth: 1,
      kind: "section",
      parentId: null,
      childIds: [],
      chapter: job.chapter || "",
      keywords: [],
      job: null,
      partIds: [],
      order: entries.length,
    });
    // Merge onto whichever entry won the key — an outline heading keeps its own numbering.
    if (!entry.job) {
      entry.job = job;
      entry.chapter = entry.chapter || job.chapter || "";
      entry.partIds = Array.isArray(job.partIds) ? job.partIds : [];
      if (Array.isArray(job.keywords)) entry.keywords = job.keywords;
      // A leaf heading gets the section's measured range; a chapter keeps its own span.
      if (!entry.childIds.length) entry.pageEnd = Math.max(entry.page, jobEnd(job));
    }
  }

  for (const entry of entries) {
    entry.terms = terms(entry);
    entry.titleFold = fold(entry.title);
    entry.textFold = fold(`${entry.title} ${entry.chapter} ${entry.keywords.join(" ")}`);
    entry.lower = entry.label.toLowerCase();
  }
  return entries;
}

/** The manual's own top level — what the list shows before anyone types. */
export function roots(entries) {
  return (entries || []).filter((e) => e.parentId == null && e.kind === "chapter");
}

/** id -> entry, so pick.js can walk childIds without rescanning the list. */
export function byId(entries) {
  return new Map((entries || []).map((e) => [e.id, e]));
}

/* ------------------------------------------------------------------ search */

function scoreToken(entry, qt, qGrams, maxDl) {
  for (const term of entry.terms) {
    if (term.t === qt) return TIER_EXACT;
  }
  for (const term of entry.terms) {
    if (term.t.startsWith(qt)) return TIER_PREFIX;
  }
  if (entry.titleFold.includes(qt)) return TIER_TITLE;
  if (entry.textFold.includes(qt)) return TIER_TEXT;
  if (qGrams.size) {
    for (const term of entry.terms) {
      if (gramSim(qGrams, term.grams) >= 0.5) return TIER_GRAM;
    }
  }
  if (qt.length >= 3) {
    for (const term of entry.terms) {
      if (Math.abs(term.len - qt.length) > maxDl) continue;
      if (damerau(qt, term.t, maxDl) <= maxDl) return TIER_TYPO;
    }
  }
  return TIER_NONE;
}

/**
 * search(entries, text, limit) -> entries[]
 * Every query token must land somewhere, so typing always narrows; ties break towards the
 * heading that literally starts with what was typed, then towards a real indexed section,
 * then by page, so the order reads like the manual.
 */
export function search(entries, text, limit = 60) {
  const list = entries || [];
  const qTokens = tokens(text);
  if (!qTokens.length) return [];

  const prepared = qTokens.map((qt) => ({
    qt,
    grams: trigrams(qt),
    maxDl: qt.length <= 5 ? 1 : 2,
  }));
  const head = fold(text);

  const hits = [];
  for (const entry of list) {
    let worst = TIER_EXACT;
    let sum = 0;
    let ok = true;
    for (const p of prepared) {
      const tier = scoreToken(entry, p.qt, p.grams, p.maxDl);
      if (tier === TIER_NONE) {
        ok = false;
        break;
      }
      if (tier > worst) worst = tier;
      sum += tier;
    }
    if (!ok) continue;
    let bonus = 0;
    if (head && entry.titleFold.startsWith(head)) bonus += 2;
    else if (head && entry.titleFold.includes(head)) bonus += 1;
    if (entry.job) bonus += 1;
    hits.push({ entry, worst, sum, bonus });
  }

  hits.sort((a, b) => {
    if (a.worst !== b.worst) return a.worst - b.worst;
    if (a.sum !== b.sum) return a.sum - b.sum;
    if (a.bonus !== b.bonus) return b.bonus - a.bonus;
    if (a.entry.page !== b.entry.page) return a.entry.page - b.entry.page;
    return a.entry.order - b.entry.order;
  });

  const cap = Number.isFinite(limit) ? Math.max(0, limit) : hits.length;
  return hits.slice(0, cap).map((h) => h.entry);
}

/**
 * Character ranges of `text` inside a heading, for marking the hit. Folded on both sides, so
 * "brakefluid" still marks "Brake fluid" and accents never break the offsets.
 */
export function marks(title, text) {
  const raw = String(title == null ? "" : title);
  const qs = tokens(text);
  if (!raw || !qs.length) return [];
  const map = [];
  let folded = "";
  const flat = raw.normalize("NFD").replace(/\p{M}/gu, "");
  for (let i = 0; i < flat.length; i++) {
    const c = flat[i].toLowerCase();
    if ((c >= "a" && c <= "z") || (c >= "0" && c <= "9")) {
      map.push(i);
      folded += c;
    }
  }
  const spans = [];
  const whole = fold(text);
  const needles = whole && folded.includes(whole) ? [whole] : qs;
  for (const q of needles) {
    let from = 0;
    for (;;) {
      const at = folded.indexOf(q, from);
      if (at < 0 || at >= map.length) break;
      const last = at + q.length - 1;
      if (last < map.length) spans.push({ start: map[at], end: map[last] + 1 });
      from = at + q.length;
    }
  }
  if (!spans.length) return [];
  spans.sort((a, b) => a.start - b.start || a.end - b.end);
  const out = [spans[0]];
  for (let i = 1; i < spans.length; i++) {
    const prev = out[out.length - 1];
    if (spans[i].start <= prev.end) prev.end = Math.max(prev.end, spans[i].end);
    else out.push(spans[i]);
  }
  return out;
}

/** The page list a synthesised job opens with — the heading's own range, capped. */
export function spanOf(entry) {
  if (!entry) return [1];
  const from = Math.max(1, Number(entry.page) || 1);
  const to = Math.max(from, Number(entry.pageEnd) || from);
  const span = Math.min(to - from + 1, MAX_SPAN);
  const out = new Array(span);
  for (let i = 0; i < span; i++) out[i] = from + i;
  return out;
}
