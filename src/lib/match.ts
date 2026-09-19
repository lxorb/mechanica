import type { Manual, Match, Section } from '../types'

const PHRASES: [RegExp, string][] = [
  [/\btop(?:ping|ped)?[\s-]*up\b/g, 'refill'],
  [/\bfill(?:ing)?[\s-]*up\b/g, 'refill'],
  [/\banti[\s-]*freeze\b/g, 'antifreeze'],
  [/\bnewton[\s-]*met(?:er|re)s?\b/g, 'nm'],
  [/\bn[\s-]*m\b/g, 'nm'],
  [/\bhand[\s-]*bars?\b/g, 'handlebar'],
  [/\bhead[\s-]*light(?:s)?\b/g, 'headlight'],
  [/\bspark[\s-]*plug(?:s)?\b/g, 'sparkplug'],
  [/\bair[\s-]*filter(?:s)?\b/g, 'airfilter'],
]

const STOP = new Set(
  ('a an the this that these those my your our their its it i me we you he she they them' +
    ' is are am was were be been being do does did done doing have has had' +
    ' how what when where why which who whose whom' +
    ' to of for on in at by with from up out off into onto about over under around again' +
    ' and or but not no nor so if then than as too also' +
    ' can could should would will shall may might must need needs needed want wants wanted please just' +
    ' go goes going make makes making take takes taking' +
    ' there here now much many any some all every each' +
    ' bike bikes motorcycle motorbike moto s t re ve ll').split(' '),
)

const GROUPS: string[][] = [
  ['oil', 'lube', 'lubricant', 'lubrication', 'lubricate', 'grease'],
  ['tyre', 'tire'],
  ['pad', 'pads', 'lining', 'linings', 'shoe'],
  ['slack', 'tension', 'tensioning', 'play', 'sag', 'loose', 'loosen'],
  ['refill', 'fill', 'top'],
  ['replace', 'change', 'swap', 'renew', 'new'],
  ['check', 'inspect', 'inspection', 'examine', 'verify', 'look', 'test'],
  ['torque', 'tighten', 'tightening', 'nm'],
  ['coolant', 'antifreeze'],
  ['battery', 'charge', 'charging', 'charger'],
  ['fuse', 'blown', 'blow'],
  ['headlight', 'headlamp', 'beam', 'light', 'bulb'],
  ['pressure', 'psi', 'bar', 'inflate', 'inflation'],
  ['wheel', 'rim'],
  ['clutch'],
  ['front'],
  ['rear', 'back'],
  ['chain'],
  ['brake', 'braking'],
  ['engine', 'motor'],
  ['adjust', 'adjustment', 'set', 'setting'],
  ['remove', 'removal', 'detach', 'dismount'],
  ['install', 'installation', 'mount', 'fit', 'refit'],
  ['clean', 'cleaning', 'wash'],
  ['level', 'amount', 'quantity'],
  ['wear', 'worn', 'thickness'],
]

function stem(word: string): string {
  let t = word
  if (t.length > 4 && t.endsWith('ies')) t = t.slice(0, -3) + 'y'
  else if (t.length > 5 && t.endsWith('ing')) t = t.slice(0, -3)
  else if (t.length > 4 && t.endsWith('ed')) t = t.slice(0, -2)
  else if (t.length > 3 && t.endsWith('es')) t = t.slice(0, -2)
  else if (t.length > 3 && t.endsWith('s') && !t.endsWith('ss')) t = t.slice(0, -1)
  if (t.length > 3 && t.endsWith('e')) t = t.slice(0, -1)
  return t
}

const SYNONYM = new Map<string, string>()
for (const group of GROUPS) {
  const head = stem(group[0])
  for (const word of group) SYNONYM.set(stem(word), head)
}

function normalize(text: string): string {
  let s = text.toLowerCase()
  for (const [re, to] of PHRASES) s = s.replace(re, to)
  return s.replace(/[^a-z0-9]+/g, ' ').trim()
}

function canon(text: string): string[] {
  const out: string[] = []
  for (const raw of normalize(text).split(' ')) {
    if (!raw || STOP.has(raw)) continue
    const s = stem(raw)
    if (!s) continue
    out.push(SYNONYM.get(s) ?? s)
  }
  return out
}

function contiguous(hay: string[], needle: string[]): boolean {
  if (!needle.length || needle.length > hay.length) return false
  for (let i = 0; i <= hay.length - needle.length; i++) {
    let ok = true
    for (let j = 0; j < needle.length; j++)
      if (hay[i + j] !== needle[j]) {
        ok = false
        break
      }
    if (ok) return true
  }
  return false
}

const KEYWORD_PHRASE = 1
const KEYWORD_TOKENS = 0.7
const TITLE_TOKEN = 0.5
const CHAPTER_TOKEN = 0.2
const TITLE_TOKEN_CAP = 6
const THRESHOLD = 0.25
const LIMIT = 4

function rawScore(section: Section, queryRaw: string, querySeq: string[], queryTokens: Set<string>): number {
  let keyword = 0
  for (const k of section.keywords) {
    const kRaw = normalize(k)
    const kSeq = canon(k)
    if (!kSeq.length) continue
    if (` ${queryRaw} `.includes(` ${kRaw} `) || contiguous(querySeq, kSeq)) keyword = Math.max(keyword, KEYWORD_PHRASE)
    else if (kSeq.every((t) => queryTokens.has(t))) keyword = Math.max(keyword, KEYWORD_TOKENS)
    if (keyword === KEYWORD_PHRASE) break
  }

  const titleTokens = new Set(canon(section.title))
  let title = 0
  for (const t of queryTokens) if (titleTokens.has(t)) title += TITLE_TOKEN
  title = Math.min(title, TITLE_TOKEN * TITLE_TOKEN_CAP)

  const chapterTokens = new Set(canon(section.chapter))
  let chapter = 0
  for (const t of queryTokens)
    if (chapterTokens.has(t)) {
      chapter = CHAPTER_TOKEN
      break
    }

  return keyword + title + chapter
}

export function match(manual: Manual, query: string): Match[] {
  const queryRaw = normalize(query)
  const querySeq = canon(query)
  const queryTokens = new Set(querySeq)
  if (!queryTokens.size) return []

  const best = KEYWORD_PHRASE + TITLE_TOKEN * Math.min(queryTokens.size, TITLE_TOKEN_CAP) + CHAPTER_TOKEN

  return manual.sections
    .map((section) => ({ section, score: Math.min(1, rawScore(section, queryRaw, querySeq, queryTokens) / best) }))
    .filter((m) => m.score >= THRESHOLD)
    .sort((a, b) => b.score - a.score || a.section.pageStart - b.section.pageStart)
    .slice(0, LIMIT)
}
