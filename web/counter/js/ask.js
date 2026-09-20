/**
 * Ask, backed by the API. The on-device QA model is gone: ask() posts to /ask through the
 * adapter and hands back the manual's own sections, one row per hit, with the page to open.
 * Exported names are unchanged for the screens that already use them.
 */

import { ask as askApi, bike, jobById, pageTextUrl } from "./ttm.js";

export { pageTextUrl };

export function jobPageNums(job) {
  const nums = [];
  const seen = new Set();
  for (const n of (job && job.pages) || []) {
    if (n == null || seen.has(n)) continue;
    seen.add(n);
    nums.push(n);
  }
  for (const row of (job && job.related) || []) {
    const n = row && typeof row === "object" ? row.page : null;
    if (n == null || seen.has(n)) continue;
    seen.add(n);
    nums.push(n);
  }
  return nums;
}

/** Page text for a job. Falls back to bare page numbers when a manual ships as PDF only. */
export async function fetchJobPages(job) {
  const manualId = job && job.manualId;
  if (!manualId) return [];
  const nums = jobPageNums(job);
  const pages = [];
  for (const n of nums) {
    const url = pageTextUrl(manualId, n);
    if (!url) continue;
    try {
      const res = await fetch(url);
      if (!res.ok) continue;
      const text = await res.text();
      if (String(text).trim()) pages.push({ manualId, n, text: String(text) });
    } catch {
      /* missing page text */
    }
  }
  if (pages.length) return pages;
  return nums.map((n) => ({ manualId, n, text: "" }));
}

/** Nothing to download any more; kept so callers can keep their progress plumbing. */
export function loadAsk(onProgress) {
  if (typeof onProgress === "function") {
    try {
      onProgress({ status: "ready", progress: 100 });
    } catch {
      /* progress is best-effort */
    }
  }
  return Promise.resolve(true);
}

function indexFlexible(hay, needle) {
  const src = String(hay || "");
  const want = String(needle || "").trim();
  if (!want) return null;
  const exact = src.indexOf(want);
  if (exact >= 0) return { start: exact, end: exact + want.length };
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
  return { start: map[at], end: map[at + compactNeedle.length - 1] + 1 };
}

function manualOf(source) {
  if (typeof source === "string") return source;
  if (Array.isArray(source)) {
    for (const page of source) {
      if (page && page.manualId) return page.manualId;
    }
    return "";
  }
  if (source && typeof source === "object" && source.manualId) return source.manualId;
  return "";
}

export function jobsOf(res) {
  if (Array.isArray(res)) return res;
  if (res && Array.isArray(res.jobs)) return res.jobs;
  return [];
}

/** Ask the manual. `source` is a manual id, a job, or the page rows a screen already holds. */
export async function askJobs(query, source) {
  const q = String(query || "").trim();
  if (!q) return [];
  let manualId = manualOf(source);
  if (!manualId) {
    const state = typeof window !== "undefined" && window.HandyBus ? window.HandyBus.state : null;
    if (state && state.jobId) {
      try {
        const job = await jobById(state.jobId);
        manualId = (job && job.manualId) || "";
      } catch {
        /* fall through */
      }
    }
    if (!manualId && state && state.bikeId) {
      const rec = bike(state.bikeId);
      manualId = (rec && rec.manualId) || "";
    }
  }
  if (!manualId) return [];
  let res;
  try {
    res = await askApi(manualId, q);
  } catch {
    return [];
  }
  return jobsOf(res);
}

/** Hit rows: one per matching section, shaped like the spans the book sheet already paints. */
export async function ask(question, source) {
  const jobs = await askJobs(question, source);
  const pages = Array.isArray(source) ? source : [];
  const rows = [];
  for (const job of jobs) {
    const page = (job.pages && job.pages[0] != null ? job.pages[0] : job.pageStart) ?? null;
    if (page == null) continue;
    const title = String(job.title || "");
    const text = (pages.find((p) => p && p.n === page) || {}).text || "";
    const at = text ? indexFlexible(text, title) : null;
    rows.push({
      answer: title,
      page,
      start: at ? at.start : 0,
      end: at ? at.end : 0,
      score: Number(job.score) || 1,
      manualId: job.manualId,
      jobId: job.id,
    });
  }
  return rows;
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
