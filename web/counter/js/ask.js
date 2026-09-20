import { pageTextUrl } from "./query.js";

export { pageTextUrl };

const MODEL_ID = "Xenova/distilbert-base-cased-distilled-squad";
const TRANSFORMERS_URL = "https://cdn.jsdelivr.net/npm/@xenova/transformers@2.17.2";
const TOP_K = 3;
const SCORE_MIN = 0.15;
const SPANS_PER_PASSAGE = 2;
const BM25_K1 = 1.5;
const BM25_B = 0.75;
const STOP = new Set([
  "a",
  "an",
  "the",
  "is",
  "are",
  "was",
  "were",
  "be",
  "of",
  "and",
  "or",
  "to",
  "in",
  "on",
  "for",
  "with",
  "what",
  "which",
  "who",
  "how",
  "do",
  "does",
  "did",
  "this",
  "that",
]);

let loading = null;
let qaPipe = null;

const CHUNK = 280;

export function tokenize(text) {
  const normalized = String(text || "")
    .toLowerCase()
    .replace(/[·•]/g, " ")
    .replace(/\bn\s+m\b/g, " nm ");
  return normalized.match(/[a-z0-9]+/g) || [];
}

function expandQuery(query) {
  const q = String(query || "");
  const low = q.toLowerCase();
  const extra = [];
  if (/\btorque\b/.test(low)) extra.push("tightening", "nm", "kgf", "lbft");
  if (/capacit|quantity|how much/.test(low)) extra.push("qt", "draining", "change", "liter", "litre");
  if (/grade/.test(low)) extra.push("sae", "10w", "jaso", "viscosity", "recommended");
  return extra.length ? `${q} ${extra.join(" ")}` : q;
}

function answerFits(question, answer) {
  const q = String(question || "").toLowerCase();
  const a = String(answer || "")
    .toLowerCase()
    .replace(/[·•]/g, " ");
  if (/\btorque\b/.test(q)) return /n\s*m|kgf|lb\s*ft|lbf/.test(a);
  if (/capacit|quantity|how much/.test(q)) return /\bqt\b|\bl\b|liter|litre|\bml\b/.test(a);
  if (/grade/.test(q)) return /sae|\d+\s*w\b|jaso|api|viscosity/.test(a);
  return true;
}

function splitLong(text) {
  const src = String(text || "").trim();
  if (!src) return [];
  if (src.length <= CHUNK) return [src];
  const lines = src.split(/\n/);
  const chunks = [];
  let buf = "";
  for (const line of lines) {
    if (buf && buf.length + line.length + 1 > CHUNK) {
      chunks.push(buf.trim());
      const overlap = buf.slice(-40);
      buf = overlap + "\n" + line;
      if (buf.length > CHUNK * 1.5) buf = line;
    } else {
      buf = buf ? `${buf}\n${line}` : line;
    }
  }
  if (buf.trim()) chunks.push(buf.trim());
  return chunks;
}

export function splitPassages(pages) {
  const out = [];
  for (const page of pages || []) {
    const pageText = String(page && page.text != null ? page.text : "");
    const parts = pageText
      .split(/\n\s*\n/)
      .map((part) => part.trim())
      .filter(Boolean);
    const paras = parts.length ? parts : pageText.trim() ? [pageText.trim()] : [];
    for (const para of paras) {
      for (const chunk of splitLong(para)) {
        out.push({
          manualId: page.manualId,
          n: page.n,
          pageText,
          text: chunk,
        });
      }
    }
  }
  return out;
}

export function bm25Top(query, passages, k = TOP_K) {
  const raw = tokenize(expandQuery(query));
  const terms = raw.filter((t) => !STOP.has(t) && t.length > 1);
  const qTerms = terms.length ? terms : raw;
  if (!qTerms.length || !passages || !passages.length) return [];

  const docs = passages.map((p) => tokenize(p.text));
  const nDocs = docs.length;
  const avgdl = docs.reduce((sum, doc) => sum + doc.length, 0) / nDocs || 1;
  const df = new Map();
  for (const doc of docs) {
    const seen = new Set(doc);
    for (const t of seen) df.set(t, (df.get(t) || 0) + 1);
  }

  function idf(term) {
    const n = df.get(term) || 0;
    return Math.log((nDocs - n + 0.5) / (n + 0.5) + 1);
  }

  const ranked = passages.map((passage, i) => {
    const doc = docs[i];
    const tf = new Map();
    for (const t of doc) tf.set(t, (tf.get(t) || 0) + 1);
    const dl = doc.length || 1;
    let score = 0;
    for (const term of qTerms) {
      const f = tf.get(term) || 0;
      if (!f) continue;
      const denom = f + BM25_K1 * (1 - BM25_B + BM25_B * (dl / avgdl));
      score += idf(term) * ((f * (BM25_K1 + 1)) / denom);
    }
    return { ...passage, bm25: score };
  });

  ranked.sort((a, b) => b.bm25 - a.bm25 || (a.n ?? 0) - (b.n ?? 0));
  return ranked.filter((row) => row.bm25 > 0).slice(0, k);
}

export function jobPageNums(job) {
  const nums = [];
  const seen = new Set();
  for (const n of (job && job.pages) || []) {
    if (n == null || seen.has(n)) continue;
    seen.add(n);
    nums.push(n);
  }
  for (const row of (job && job.related) || []) {
    const n = row && row.page;
    if (n == null || seen.has(n)) continue;
    seen.add(n);
    nums.push(n);
  }
  return nums;
}

export async function fetchJobPages(job) {
  const manualId = job && job.manualId;
  if (!manualId) return [];
  const pages = [];
  for (const n of jobPageNums(job)) {
    try {
      const res = await fetch(pageTextUrl(manualId, n));
      if (!res.ok) continue;
      const text = await res.text();
      if (String(text).trim()) pages.push({ manualId, n, text: String(text) });
    } catch {
      /* missing page text */
    }
  }
  return pages;
}

export function loadAsk(onProgress) {
  if (qaPipe) return Promise.resolve(qaPipe);
  if (loading) return loading;
  loading = import(TRANSFORMERS_URL)
    .then((mod) => {
      const { pipeline, env } = mod;
      env.allowLocalModels = false;
      env.useBrowserCache = true;
      return pipeline("question-answering", MODEL_ID, {
        progress_callback: typeof onProgress === "function" ? onProgress : undefined,
      });
    })
    .then((pipe) => {
      qaPipe = pipe;
      loading = null;
      return pipe;
    })
    .catch((err) => {
      loading = null;
      throw err;
    });
  return loading;
}

function indexFlexible(hay, needle) {
  const src = String(hay || "");
  const want = String(needle || "").trim();
  if (!want) return null;
  const exact = src.indexOf(want);
  if (exact >= 0) return { start: exact, end: exact + want.length, answer: src.slice(exact, exact + want.length) };
  const compactNeedle = want.replace(/\s+/g, "");
  if (!compactNeedle) return null;
  const map = [];
  let compact = "";
  for (let i = 0; i < src.length; i++) {
    if (/\s/.test(src[i])) continue;
    map.push(i);
    compact += src[i];
  }
  const at = compact.indexOf(compactNeedle);
  if (at < 0) return null;
  const start = map[at];
  const end = map[at + compactNeedle.length - 1] + 1;
  return { start, end, answer: src.slice(start, end) };
}

function isPlausible(answer) {
  const a = String(answer || "").trim();
  if (a.length < 2) return false;
  if (/^\d+\s*P\.\s*\d+/i.test(a)) return false;
  if (/^\d{1,3}$/.test(a)) return false;
  return true;
}

function locateSpan(pageText, context, raw) {
  const answer = String(raw && raw.answer != null ? raw.answer : "").trim();
  if (!answer || !isPlausible(answer)) return null;
  const ctx = String(context || "");
  const page = String(pageText || "");
  let start = Number(raw.start);
  let end = Number(raw.end);
  let ctxHit = null;
  if (Number.isFinite(start) && Number.isFinite(end) && end > start) {
    const slice = ctx.slice(start, end);
    if (slice && (slice === answer || slice.replace(/\s+/g, "") === answer.replace(/\s+/g, ""))) {
      ctxHit = { start, end, answer: slice };
    }
  }
  if (!ctxHit) ctxHit = indexFlexible(ctx, answer);
  if (ctxHit) {
    const base = page.indexOf(ctx);
    if (base >= 0) {
      const pageStart = base + ctxHit.start;
      const pageEnd = pageStart + ctxHit.answer.length;
      const verbatim = page.slice(pageStart, pageEnd);
      if (verbatim) return { start: pageStart, end: pageEnd, answer: verbatim };
    }
  }
  return indexFlexible(page, answer);
}

function maskSpan(text, start, end) {
  if (end <= start) return text;
  return text.slice(0, start) + " ".repeat(end - start) + text.slice(end);
}

async function spansFromPassage(pipe, question, passage) {
  const hits = [];
  let context = passage.text;
  for (let i = 0; i < SPANS_PER_PASSAGE; i++) {
    if (!context.trim()) break;
    let raw;
    try {
      raw = await callQa(pipe, question, context);
    } catch {
      break;
    }
    if (!raw) break;
    const score = Number(raw.score);
    if (!Number.isFinite(score) || score < SCORE_MIN) break;
    const located = locateSpan(passage.pageText || passage.text, context, raw);
    if (!located || !answerFits(question, located.answer)) {
      const flex = indexFlexible(context, raw.answer);
      if (flex) context = maskSpan(context, flex.start, flex.end);
      else break;
      continue;
    }
    hits.push({
      answer: located.answer,
      page: passage.n,
      start: located.start,
      end: located.end,
      score,
      manualId: passage.manualId,
    });
    const ctxHit = indexFlexible(context, located.answer) || indexFlexible(context, raw.answer);
    if (!ctxHit) break;
    context = maskSpan(context, ctxHit.start, ctxHit.end);
  }
  return hits;
}

async function callQa(pipe, question, context) {
  const attempts = [
    () => pipe({ question, context }),
    () => pipe(question, context),
    () => pipe(question, { context }),
  ];
  let lastErr;
  for (const run of attempts) {
    try {
      const raw = await run();
      const row = Array.isArray(raw) ? raw[0] : raw;
      if (row && row.answer != null) return row;
      if (row && row.text != null) {
        return { answer: row.text, score: row.score, start: row.start, end: row.end };
      }
    } catch (err) {
      lastErr = err;
    }
  }
  if (lastErr) throw lastErr;
  return null;
}

export async function ask(question, pages) {
  const q = String(question || "").trim();
  if (!q) return [];
  const passages = bm25Top(q, splitPassages(pages), TOP_K);
  if (!passages.length) return [];
  let pipe;
  try {
    pipe = await loadAsk();
  } catch {
    return [];
  }
  const found = [];
  for (const passage of passages) {
    try {
      const hits = await spansFromPassage(pipe, q, passage);
      found.push(...hits);
    } catch {
      /* skip passage */
    }
  }
  found.sort((a, b) => b.score - a.score);
  const uniq = [];
  const seen = new Set();
  for (const hit of found) {
    if (hit.score < SCORE_MIN) continue;
    const key = `${hit.page}:${hit.start}:${hit.end}`;
    if (seen.has(key)) continue;
    seen.add(key);
    uniq.push(hit);
    if (uniq.length >= TOP_K) break;
  }
  return uniq;
}

export function contextWindow(text, start, end, limit = 160) {
  const src = String(text || "");
  const a = Math.max(0, Math.min(src.length, Number(start) || 0));
  const b = Math.max(a, Math.min(src.length, Number(end) || a));
  const span = src.slice(a, b);
  if (!span) return { text: "", start: 0, end: 0 };

  let from = a;
  while (from > 0 && !".!?\n".includes(src[from - 1])) from -= 1;
  let to = b;
  while (to < src.length && !".!?\n".includes(src[to])) to += 1;
  if (to < src.length && ".!?".includes(src[to])) to += 1;

  const sentence = src.slice(from, to).replace(/\s+/g, " ").trim();
  const flatSpan = span.replace(/\s+/g, " ").trim();
  let local = sentence.indexOf(flatSpan);
  if (local < 0) local = 0;
  const localEnd = local + flatSpan.length;

  if (sentence.length <= limit) {
    return { text: sentence, start: local, end: localEnd };
  }

  const room = Math.max(0, limit - flatSpan.length);
  const left = Math.min(local, Math.floor(room / 2));
  let winFrom = local - left;
  let winTo = winFrom + limit;
  if (winTo > sentence.length) {
    winTo = sentence.length;
    winFrom = Math.max(0, winTo - limit);
  }
  return {
    text: sentence.slice(winFrom, winTo),
    start: local - winFrom,
    end: localEnd - winFrom,
  };
}
