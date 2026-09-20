const TIER_EXACT = 0;
const TIER_PREFIX = 1;
const TIER_TRIGRAM = 2;
const TIER_TYPO = 3;
const TIER_NONE = 9;
export const MAX_QUERY_TOKENS = 12;

let rows = [];

export function fold(value) {
  return String(value ?? "")
    .toLowerCase()
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .replace(/[^a-z0-9]+/g, "");
}

export function tokens(value) {
  return String(value ?? "")
    .toLowerCase()
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .split(/[^a-z0-9]+/)
    .filter(Boolean);
}

function trigramsOf(s) {
  const n = s.length;
  if (n < 3) return [];
  const out = new Array(n - 2);
  for (let i = 0; i <= n - 3; i++) out[i] = s.slice(i, i + 3);
  return out;
}

function trigramSim(qGrams, haySet) {
  const n = qGrams.length;
  if (!n) return 0;
  let hit = 0;
  for (let i = 0; i < n; i++) if (haySet.has(qGrams[i])) hit++;
  return hit / n;
}

function damerau(a, b, max) {
  const n = a.length;
  const m = b.length;
  if (Math.abs(n - m) > max) return max + 1;
  if (n === 0) return m;
  if (m === 0) return n;

  const prev2 = new Array(m + 1);
  const prev = new Array(m + 1);
  const cur = new Array(m + 1);
  for (let j = 0; j <= m; j++) prev[j] = j;

  for (let i = 1; i <= n; i++) {
    cur[0] = i;
    let rowMin = i;
    const ai = a[i - 1];
    const ai2 = i > 1 ? a[i - 2] : "";
    for (let j = 1; j <= m; j++) {
      const cost = ai === b[j - 1] ? 0 : 1;
      let v = prev[j] + 1;
      const ins = cur[j - 1] + 1;
      const sub = prev[j - 1] + cost;
      if (ins < v) v = ins;
      if (sub < v) v = sub;
      if (i > 1 && j > 1 && ai === b[j - 2] && ai2 === b[j - 1]) {
        const tr = prev2[j - 2] + 1;
        if (tr < v) v = tr;
      }
      cur[j] = v;
      if (v < rowMin) rowMin = v;
    }
    if (rowMin > max) return max + 1;
    for (let j = 0; j <= m; j++) {
      prev2[j] = prev[j];
      prev[j] = cur[j];
    }
  }
  return prev[m];
}

function yearsOf(bike) {
  const out = new Set();
  if (bike.year != null && bike.year !== "") out.add(String(bike.year));
  if (Array.isArray(bike.years)) {
    for (const y of bike.years) {
      if (y != null && y !== "") out.add(String(y));
    }
  }
  return out;
}

function addField(into, value) {
  if (value == null || value === "") return;
  const ts = tokens(value);
  for (let i = 0; i < ts.length; i++) into.add(ts[i]);
  const f = fold(value);
  if (f) into.add(f);
}

export function fieldTokens(bike) {
  const general = new Set();
  addField(general, bike.make);
  addField(general, bike.model);
  if (Array.isArray(bike.aliases)) {
    for (let i = 0; i < bike.aliases.length; i++) addField(general, bike.aliases[i]);
  }

  const makeFold = fold(bike.make);
  if (makeFold) {
    const extras = [];
    for (const t of general) {
      if (t !== makeFold) extras.push(makeFold + t);
    }
    for (let i = 0; i < extras.length; i++) general.add(extras[i]);
  }

  const joined = fold([bike.make, bike.model, ...(Array.isArray(bike.aliases) ? bike.aliases : [])].join(""));
  if (joined) general.add(joined);

  const cc = bike.cc == null || bike.cc === "" ? "" : fold(bike.cc);
  return { general, years: yearsOf(bike), cc };
}

function matchAgainstToken(qt, hay, qGrams, qLen, maxDl) {
  if (hay === qt) return { tier: TIER_EXACT, sim: 1 };
  if (hay.startsWith(qt)) return { tier: TIER_PREFIX, sim: 1 };
  if (qGrams.length) {
    const sim = trigramSim(qGrams, new Set(trigramsOf(hay)));
    if (sim >= 0.5) return { tier: TIER_TRIGRAM, sim };
  }
  if (qLen >= 3 && damerau(qt, hay, maxDl) <= maxDl) return { tier: TIER_TYPO, sim: 0 };
  return { tier: TIER_NONE, sim: 0 };
}

function matchQueryToken(qt, row, qGrams, qLen, maxDl) {
  if (row.years.has(qt) || (row.cc && row.cc === qt)) {
    return { tier: TIER_EXACT, sim: 1 };
  }
  if (row.tokenSet.has(qt)) return { tier: TIER_EXACT, sim: 1 };

  const grams = row.grams;
  for (let i = 0; i < grams.length; i++) {
    if (grams[i].token.startsWith(qt)) return { tier: TIER_PREFIX, sim: 1 };
  }

  if (qGrams.length) {
    let best = 0;
    for (let i = 0; i < grams.length; i++) {
      const sim = trigramSim(qGrams, grams[i].gramSet);
      if (sim > best) best = sim;
      if (best === 1) break;
    }
    if (best >= 0.5) return { tier: TIER_TRIGRAM, sim: best };
  }

  if (qLen >= 3) {
    for (let i = 0; i < grams.length; i++) {
      const hay = grams[i].token;
      if (Math.abs(hay.length - qLen) > maxDl) continue;
      if (damerau(qt, hay, maxDl) <= maxDl) return { tier: TIER_TYPO, sim: 0 };
    }
  }

  return { tier: TIER_NONE, sim: 0 };
}

export function buildIndex(bikes) {
  const list = Array.isArray(bikes) ? bikes : [];
  const next = new Array(list.length);
  for (let i = 0; i < list.length; i++) {
    const bike = list[i];
    const { general, years, cc } = fieldTokens(bike);
    const tokenList = Array.from(general);
    const grams = new Array(tokenList.length);
    for (let t = 0; t < tokenList.length; t++) {
      const token = tokenList[t];
      const g = trigramsOf(token);
      grams[t] = { token, gramSet: new Set(g), len: token.length };
    }
    next[i] = {
      bike,
      tokenSet: general,
      grams,
      years,
      cc,
      hasManual: !!bike.manualId,
      makeModel: `${bike.make ?? ""} ${bike.model ?? ""}`,
      yearNum: Number(bike.year) || 0,
    };
  }
  rows = next;
}

export function indexedCount() {
  return rows.length;
}

export function search(text, opts) {
  const limit = opts && opts.limit != null ? opts.limit : 60;
  // Every token is scored against every one of 27.4k rows, so a pasted paragraph of words that
  // all happen to match (a VIN dump, a stuck key) is minutes of work on the main thread. Nobody
  // narrows a bike with more words than this, and the ones past it cannot change the answer.
  const qTokens = tokens(text).slice(0, MAX_QUERY_TOKENS);
  if (!qTokens.length) return rows.map((row) => row.bike);

  const prepared = qTokens.map((qt) => ({
    qt,
    qGrams: trigramsOf(qt),
    qLen: qt.length,
    maxDl: qt.length <= 5 ? 1 : 2,
  }));

  const hits = [];
  for (let i = 0; i < rows.length; i++) {
    const row = rows[i];
    let worst = TIER_EXACT;
    let sumTier = 0;
    let sumSim = 0;
    let ok = true;
    for (let q = 0; q < prepared.length; q++) {
      const p = prepared[q];
      const got = matchQueryToken(p.qt, row, p.qGrams, p.qLen, p.maxDl);
      if (got.tier === TIER_NONE) {
        ok = false;
        break;
      }
      if (got.tier > worst) worst = got.tier;
      sumTier += got.tier;
      sumSim += got.sim;
    }
    if (!ok) continue;
    hits.push({
      bike: row.bike,
      worst,
      sumTier,
      sumSim,
      hasManual: row.hasManual,
      makeModel: row.makeModel,
      yearNum: row.yearNum,
    });
  }

  hits.sort((a, b) => {
    if (a.worst !== b.worst) return a.worst - b.worst;
    if (a.sumTier !== b.sumTier) return a.sumTier - b.sumTier;
    if (a.sumSim !== b.sumSim) return b.sumSim - a.sumSim;
    if (a.hasManual !== b.hasManual) return (b.hasManual ? 1 : 0) - (a.hasManual ? 1 : 0);
    const name = a.makeModel.localeCompare(b.makeModel, "en");
    if (name) return name;
    return b.yearNum - a.yearNum;
  });

  const cap = Number.isFinite(limit) ? Math.max(0, limit) : hits.length;
  const out = new Array(Math.min(cap, hits.length));
  for (let i = 0; i < out.length; i++) out[i] = hits[i].bike;
  return out;
}

/**
 * Folded text plus, for every folded character, where it starts and ends in the ORIGINAL string.
 *
 * The offsets are what a caller paints a <mark> with, so they have to index the string it is
 * painting. Normalising the whole label first and then counting characters in the *normalised*
 * copy silently shifted every offset on a title that was already decomposed ("e" + U+0301 is two
 * code points that fold to one), which marked the wrong letters. Fold one code point at a time
 * instead, and let a span swallow the combining marks that trail its base letter so an accent is
 * never sliced off the end of a highlight.
 */
export function foldWithMap(str) {
  const raw = String(str ?? "");
  const folded = [];
  const map = [];
  const ends = [];
  let i = 0;
  while (i < raw.length) {
    const ch = String.fromCodePoint(raw.codePointAt(i));
    const next = i + ch.length;
    const c = ch.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
    if (c.length === 1 && ((c >= "a" && c <= "z") || (c >= "0" && c <= "9"))) {
      map.push(i);
      ends.push(next);
      folded.push(c);
    } else if (/\p{M}/u.test(ch) && ends.length) {
      ends[ends.length - 1] = next; // a combining mark belongs to the letter it sits on
    }
    i = next;
  }
  return { folded: folded.join(""), map, ends };
}

function mergeRanges(ranges) {
  if (!ranges.length) return [];
  const sorted = ranges.slice().sort((a, b) => a.start - b.start || a.end - b.end);
  const out = [{ start: sorted[0].start, end: sorted[0].end }];
  for (let i = 1; i < sorted.length; i++) {
    const prev = out[out.length - 1];
    const cur = sorted[i];
    if (cur.start <= prev.end) prev.end = Math.max(prev.end, cur.end);
    else out.push({ start: cur.start, end: cur.end });
  }
  return out;
}

export function displayLabel(bike) {
  return `${bike?.make ?? ""} ${bike?.model ?? ""}`.trim();
}

export function highlight(bike, text) {
  const label = displayLabel(bike);
  const qTokens = tokens(text);
  if (!label || !qTokens.length) return [];

  const { general, years, cc } = fieldTokens(bike);
  const tokenList = Array.from(general);
  const { folded, map, ends } = foldWithMap(label);
  const ranges = [];

  for (let q = 0; q < qTokens.length; q++) {
    const qt = qTokens[q];
    const qGrams = trigramsOf(qt);
    const qLen = qt.length;
    const maxDl = qLen <= 5 ? 1 : 2;

    let bestToken = "";
    let bestTier = TIER_NONE;
    if (years.has(qt) || (cc && cc === qt)) {
      bestToken = qt;
      bestTier = TIER_EXACT;
    } else {
      for (let t = 0; t < tokenList.length; t++) {
        const hay = tokenList[t];
        const got = matchAgainstToken(qt, hay, qGrams, qLen, maxDl);
        if (got.tier < bestTier) {
          bestTier = got.tier;
          bestToken = hay;
          if (bestTier === TIER_EXACT) break;
        }
      }
    }
    if (bestTier === TIER_NONE) continue;

    const needle = folded.includes(bestToken) ? bestToken : folded.includes(qt) ? qt : "";
    if (!needle) continue;
    const idx = folded.indexOf(needle);
    if (idx < 0 || idx >= map.length) continue;
    const last = idx + needle.length - 1;
    if (last >= map.length) continue;
    ranges.push({ start: map[idx], end: ends[last] });
  }

  return mergeRanges(ranges);
}
