# `find_procedure` — where the ten seconds went, and where they are now

The pitch's honest slide says turn 4 costs **9.9 s to first audio** against ~2 s for a spec turn, and that
**`find_procedure` is 85% of that worst case**: 1,970 ms and 6,519 ms in two live tool round trips against
260–770 ms for `get_spec`. This is the measurement of why, and what changed.

Everything below is measured on the **KTM 390 Duke 2024**, 2026-09-20, with
`api/.venv/Scripts/python`. Local rows are the real pipeline against the real
`api/data` FileStore — the same code the API runs, one process, one machine. Live rows are
`https://mechanica.emilvinu.ch/api`. **The live API still runs the old code**: its column is the
before, and it only becomes the after once the founder deploys.

---

## Before — which hop costs what

One cold call per utterance, every stage timed separately (`voice.find_procedure` → `ask.answer`).

| utterance | total | router | index | picker | of which TTC | cost log |
|---|---|---|---|---|---|---|
| "show me the brake fluid procedure" | **5,690** | 1,745 | 61 | 3,101 | 418 | 753 |
| "chain is loose" | 3,695 | 1,449 | 2 | 1,541 | 369 | 672 |
| "how do I get the front wheel off" | 4,645 | 1,334 | 2 | 2,550 | 357 | 731 |
| "the brake pads look worn" | 3,275 | 1,019 | 2 | 1,505 | 454 | 680 |
| "oil change interval" | 2,568 | 1,804 | 2 | — | — | 731 |
| "how do I change the oil" | 2,228 | 1,525 | 2 | — | — | 672 |
| "front axle nut torque" | 2,112 | 1,378 | 2 | — | — | 701 |
| "battery is dead" | 2,051 | 1,284 | 2 | — | — | 735 |
| "check the coolant level" | 1,926 | 1,158 | 2 | — | — | 696 |
| "what is the tyre pressure" | 1,856 | 1,135 | 2 | — | — | 689 |

Read it in one line: **the BM25 index is 2 ms. Everything else is an LLM call or a file the answer did
not need.**

Four findings.

1. **The router is the floor.** 1,019–1,804 ms on every single question, because every question goes
   through it. Reasoning effort is not the reason: measured over 12 questions, `low` and `none` came
   back at 1,284 vs 1,288 ms on the first pass — the latency is output tokens (six components and three
   rephrasings), not thinking.
2. **The picker is the tail.** It fires on the four questions whose top two sections are within 0.15 of
   each other, and costs 1,505–3,101 ms when it does. That is the 6,519 ms live call.
3. **The cost log is 672–753 ms of every call, and nobody hears it.** `ask.answer` read the whole
   shared cost log twice — once for a baseline before the router, once to diff at the end — to compute
   `usd`, a field the voice path does not even look at. Locally that is 41,612 JSON lines parsed twice.
   On the blob store it is a document fetch that **every LLM call invalidates as it writes its own cost
   event**, so no voice turn ever hits the cache.
4. **The Token Company round trip is 357–454 ms inside the picker.** It is a cost lever and a good one;
   out loud it buys that saving with silence.

### Live, deployed, before the change

`POST /api/ask` (the same pipeline; the voice tool path is behind the Worker's WAF):

| utterance | live |
|---|---|
| "show me the brake fluid procedure" | 5,035 |
| "chain is loose" | 4,165 |
| "the brake pads look worn" | 4,049 |
| "how do I get the front wheel off" | 3,578 |
| "check the coolant level" | 1,864 |
| "battery is dead" | 1,754 |
| "how do I change the oil" | 1,719 |
| "what is the tyre pressure" | 1,525 |
| "oil change interval" | 1,464 |
| "front axle nut torque" | 91 — served from the in-memory ask cache, not a cold call |

Production agrees with the bench, which is the point of quoting both.

---

## What changed

Four things, in `api/app/ask.py`, `api/app/search/local.py` and `api/app/voice.py`. Nothing in `chat.py`,
the web client or the Worker.

### 1. A sentence the rider already said in the manual's words asks no model anything

The router exists because riders do not speak in manual vocabulary. Sometimes they already do. When the
rider's own words name one printed section outright — a keyword phrase that section was indexed under,
or two thirds of its printed title — **and** the index leaves the runner-up a clear distance behind,
there is nothing left to translate and the answer is already on the table. `ask._fast`, gated on
`FAST_MARGIN = 0.80` and `FAST_EVIDENCE = 0.67`, with `search/local.evidence` supplying the second half.

Measured against the 150-query eval: **fires on 38 of the 130 in-scope queries, top-1 right on all 38,
and on none of the 20 out-of-scope ones** — those still need the router to say "unknown". The first
wrong answer only appears if the margin is opened to 0.95, so 0.80 ships with that distance in front of
it. A question after a printed **figure** is excluded outright whatever it looks like (`SPEC_CUES`): the
router is what feeds the deterministic spec path its printed spec name and kind, and a lexical hit may
never stand in for that.

### 2. A spoken turn reads no cost log

`ask.spoken()` — a context manager `voice.find_procedure` wraps its `ask.answer` call in. Inside it,
`usd` is 0.0 and the cost log is not read at all. Removes 672–753 ms locally from **every** spoken turn,
fast path or slow, and one blob fetch per turn in production.

For typed asks the log is now read **once** instead of twice: a `CostEvent` carries the wall clock it was
written at, so the baseline is free. This also **fixes a live bug**: the old index-based diff
(`events[before:]`) is only correct if both reads see the same list, and on the blob store's TTL cache
they do not. The deployed API reports **$0.088–0.092 per ask**, climbing monotonically call after call,
against a true cost of $0.00026. Timestamps cannot pick up an old tail.

### 3. The picker that does run costs less silence

Under `spoken()`, the picker skips The Token Company's compression and reasons at `none`. Measured over
12 ambiguous questions: **1,736 → 1,055 ms mean, p95 2,538 → 1,414 ms**, with the same lead section on
all 12.

### 4. The session warms the manual before the first question

`GET /voice/agent-settings` now starts `ask.warm(manualId)` on a daemon thread. The BM25 index and the
page map the picker's snippets are sliced out of are both built on first use — which, unwarmed, is the
middle of the rider's first spoken turn (61 ms locally; a whole page document on the blob store). The
greeting takes 724 ms to be spoken; the warm-up hides under it, is idempotent, and swallows its own
failures, because a warm-up may never break the session it is warming.

---

## After — same ten utterances

Median of three passes, before and after replayed **in the same process, on the same machine, in the
same minute**, alternating, index and page map warm. "Before" is the pre-change pipeline replayed
faithfully, two cost-log reads and all.

| utterance | before | after | |
|---|---:|---:|---|
| "show me the brake fluid procedure" | 5,117 | **4,351** | −766 |
| "how do I get the front wheel off" | 4,664 | **2,350** | −2,314 |
| "chain is loose" | 3,100 | **2,732** | −368 |
| "oil change interval" | 3,058 | **1,491** | −1,567 |
| "the brake pads look worn" | 2,941 | **2,391** | −550 |
| "check the coolant level" | 2,120 | **5** | −2,115 |
| "front axle nut torque" | 2,112 | **1,034** | −1,078 |
| "what is the tyre pressure" | 1,920 | **1,144** | −776 |
| "battery is dead" | 1,895 | **4** | −1,891 |
| "how do I change the oil" | 1,791 | **2,026** | +235 |

| | before | after |
|---|---:|---:|
| **p50** | **2,530 ms** | **1,758 ms** |
| mean | 2,872 ms | 1,753 ms |
| worst | 5,117 ms | 4,351 ms |
| lead section changed | — | **on none of the ten** |

The `+235 ms` row is LLM variance, not a regression: "how do I change the oil" is a single router call in
both versions, and the router's own spread over three passes is wider than that.

**What this does to the pitch's turn 4.** The tool round trip that measured 6,519 ms live is the
"brake fluid" row: router + picker + two cost-log reads. Two of those four are gone and the third is
cheaper. Turn 4 is still the slow one and should still be volunteered on stage — the remaining cost is
two honest model calls on a genuinely ambiguous question, plus the four `read_page` calls after it,
which is improvement #4 in [`improvements.md`](improvements.md) and is now unblocked (`ask.py` is no
longer owned by another agent this sprint).

---

## Measured and rejected

Two levers that looked good and are not shipped. Both are in the code as comments, with the number.

- **Raising the picker's margin out loud** so it only ran on a genuine tie. Free against the eval — over
  the 130 in-scope queries the picker fired 21 times on the typed margin of 0.85, and taking the index's
  own order instead changed top-1 on **none** of them. It is not free against reality: on
  *"how do I get the front wheel off"*, an utterance the eval does not contain, the index leads with the
  **battery** and the picker is the only thing that fixes it. A spoken answer has no page on screen to
  catch that. The picker keeps the margin it has.
- **A faster picker model** (`gpt-5.6-luna` instead of `gpt-5.6-terra`, both at reasoning `none`).
  Median 1,140 → 885 ms, p95 1,735 → 1,233, and the same 34/35 lead-in-expected over 40 ambiguous
  questions. But it disagreed on the lead section in 3 of 40 and returned an **empty** pick on a fourth —
  including *"rear wheel removal"* becoming *"threaded fasteners"*. 255 ms is not worth a wrong page a
  mechanic cannot see.

And one that measured nothing: **`reasoning` on the router**. `none` against `low` is 1,106 vs 1,322 ms
median, inside the run-to-run spread on any single question, because the router's latency is the six
components and three rephrasings it writes, not thinking about them. It ships for the spoken turn
because it is free; it is not where the seconds are.

---

## Accuracy and tests

`api/eval` — **150 queries, 130 in-scope, 20 out-of-scope.** Run four ways, ~$0.04 per run.

| run | top-1 in-scope | out-of-scope empty |
|---|---|---|
| pre-change pipeline, same process | 100.0% (130/130) → 99.2% | 100.0% |
| after, typed path | 100.0% (130/130) | 100.0% |
| after, spoken path (`spoken()` on every query) | 100.0% (130/130) → 99.2% | 100.0% |

The arrows are the honest part. **The eval is not deterministic at 100%, and it was not before this
change either.** Across four runs the misses were always one query out of 130, always on the
router → deterministic-spec path this change does not touch, and never the same one twice:
`nonen-10` *"niveau d'huile moteur"* and `typo-15` *"treed depth"*. Run on its own, `nonen-10` scores
**5 of 8** — the router labels it `spec` three times in eight and `procedure` five, and the spec branch
leads with the topping-up section instead of the level check. The pre-change pipeline missed it too, in
the same head-to-head run in which the changed one did not. `ask._fast` returns `None` for both queries,
so neither miss can come from the new path.

Sequential 150-query runs after the change: **mean 1.49 s / 1.47 s, p95 3.55 s / 3.97 s, $0.00029 and
$0.00026 per ask**, and **0.87 LLM calls per ask, down from 1.15** — that is the fast path, priced.

`api/.venv/Scripts/python -m pytest api/tests -q -x` — **638 passed, 20 skipped**, including 21 new tests
in `api/tests/test_voice_latency.py`. They are written as "this work did not happen" rather than as a
stopwatch: a wall-clock assertion on a machine that also runs 600 other tests is a flake.

## Files

`api/app/ask.py` · `api/app/search/local.py` · `api/app/voice.py` · `api/tests/test_voice_latency.py`
