# Bike/car image coverage log

One entry per cycle of `api/tools/images2.py`. Each cycle: fetch for ~60 minutes in
priority order (manual-bearing motorcycles, top-30 gap list, cars with a manual, the
tail), then `--verify` so aliases settle, then the numbers below. Read the last entry
before starting the next cycle -- "what is exhausted" is there so a cycle does not
re-spend its hour on a source that has already been emptied.

Rules that do not change: CC0 / CC BY / CC BY-SA / PD only, vision quality gate on
every candidate, credits appended to `web/store/CREDITS-bikes-2.md`, <= 2 req/s per
host, <= $2 of `images.score` per cycle, atomic checkpoints, never run git.

---

## Cycle 1 - 2026-09-20, 58 min

| | families | rows |
|---|---|---|
| overall | 3,736 -> **3,811** of 8,286 (45.2% -> 46.0%) | 16,036 -> **16,316** of 27,753 (57.8% -> 58.8%) |
| motorcycles | 3,198 -> **3,273** of 7,476 (42.9% -> 43.8%) | 12,541 -> **12,821** of 23,151 (54.2% -> 55.4%) |
| manual-bearing bikes | 1,515 -> **1,639** of 3,562 (44.3% -> 46.0%) | 8,576 -> **8,997** of 14,722 (59.7% -> 61.1%) |
| cars | 538 of 810 (66.4%, unchanged) | 3,495 of 4,602 (75.9%, unchanged) |

50 new photos (own tiles 219 -> 269), 25 new aliases. 4,536 models walked, 272
candidates rated, $0.094 of `images.score`, 49 MB on disk of a 150 MB budget.
Pass rates: category 65/163, search 33/100, wikipedia 3/9. Hits: category 25,
search 22, wikipedia 3. The denominators grew mid-cycle (another agent is still
adding rows), so the percentages move less than the absolute counts.

**What worked.** Commons *categories* remain the best source and the reason this
tool exists: a category vouches for the bike, so the filename is free to be
`DSC_0431.jpg`, which `images.py` can never accept. The alias pass -- pointing a
variant key ("RSV4 1100 Factory") at its family photo ("RSV4 1100") -- is still
1,918 of 2,187 entries, at zero bytes and zero requests. A no-candidate cache
(`web/store/img/bikes2/.misses.json`, 601 keys) now keeps each cycle off ground
already proven empty.

**What is exhausted.** The `manualId` lane (175 models) is worked out: every one
of them either has a photo or has been proven to have no free-licence photo
anywhere on Commons -- these are motocross and minibike models (YZ85, KTM 50 SX,
TT-R50E, 250 XC-F) that nobody has photographed under a free licence. Commons
*file search* is also near its floor: 33 hits from 100 rated candidates, and the
titles it still returns are increasingly the wrong displacement.

**Next leads.**
1. **Openverse is alive again.** It answered 403 (Cloudflare challenge) all of
   yesterday and answers 200 today; it is Flickr CC BY at ~1024 px, which clears
   the 640 bar and yields a 1024 hero. It is wired in behind `--openverse`.
   The catch: **200 requests/day anonymously**. An app is registered
   (credentials in `C:\Users\me\agent-secrets\openverse.txt`) but its rate limit
   stays at anonymous until someone clicks the verification e-mail. Until then
   Openverse is a scalpel for a 30-model gap list, not a sweep. Verifying that
   e-mail is the single highest-value unblock available.
2. Wiki editions were widened to en/de/ja/it/fr/es/id/th/nl this cycle but only
   3 hits came from them; ja/id/th were added at the end and have barely been
   exercised. Worth one cycle aimed only at Japanese-market models.
3. `docs/qa/images-gaps.md` (top-30 by row count) did not exist yet. When it
   lands, run it first with `--only` + `--openverse`: highest rows per photo.

---

## Cycle 2 - 2026-09-20, ~60 min (gap list + manual-bearing lane)

| | families | rows |
|---|---|---|
| overall | 3,811 -> **3,897** (+86) of 8,816 | 16,316 -> **17,068** (+752) of 30,498 |
| motorcycles | 3,273 -> **3,325** (+52) of 7,795 | 12,821 -> **13,188** (+367) of 24,135 |
| manual-bearing bikes | 1,639 -> **1,710** (+71) of 3,950 | 8,997 -> **9,415** (+418) of 15,878 |
| cars | 538 -> **572** (+34) of 1,021 | 3,495 -> **3,880** (+385) of 6,363 |

**Percentages fell while every count rose**: the catalog grew from 8,286 to 8,816
families and 27,753 to 30,498 rows mid-cycle (cars alone 810 -> 1,021). Judge this
cycle by the absolute columns.

10 new photos (own tiles 269 -> 279), 24 keys filled from a longer name, 52 new
aliases. $0.12 of `images.score`, 51 MB of 150 MB.

**What worked.** The top-30 gap list was by far the best value: 7 photos covering
178 catalog rows (Ford Explorer/F-150/Expedition, Chevrolet Tahoe, Toyota Corolla,
Buick Enclave, Subaru Legacy) - roughly 25 rows per photo, against ~1.2 rows per
photo in the open lane. **Run the gap list first, every cycle.** The
`--lengthen` pass took 24 of the 67 free keys the gap doc identified.

**What is exhausted.**
- The `manualId` lane is finished: 162 models walked this cycle for **zero** hits.
- Commons has been picked clean on the residue cycle 1 rejected: category 1/45,
  search 0/31, wikipedia 0/4. Cycle 1 took every winner these queries can reach.
- **Openverse contributed nothing.** It is reachable, but it has no free-licence
  photos of the models that are missing (KX65, YZ85, KTM 50 SX all returned 0
  results). The cars above came from Commons search, not Openverse. Still capped
  at 200 requests/day; the verification e-mail is still unclicked, but on this
  evidence lifting it is worth much less than it looked yesterday.
- The remaining 43 of the 67 "rename" keys are **deliberately declined**: 30 have
  no digit in the name (Explorer / Discovery: exactly the hazard the gap doc
  warns about) and 1 would cross a digit run. Taking them needs a human to say
  which are safe, not a rule.

**Bug fixed.** `--retry-misses` was overwriting the no-candidate cache instead of
ignoring it for selection only, so the scoped gap-list run erased 580 cached dead
ends and the main lane then re-walked them. That cost this cycle most of its hour.
The cache is now always carried forward (`skip_misses` vs `misses`).

**Next leads, in order.**
1. Ask whoever generates `images-gaps.md` for a **top-200**, not a top-30. It is
   the only lane with real density left, and 27 entries is under ten minutes of work.
2. Commons categories per **make** (`Category:Kawasaki motorcycles` and its
   subcategories) rather than per model - the only Commons seam not yet worked.
3. ja/id/th Wikipedia are wired but barely exercised (4 article hits all cycle);
   they need a JDM-model list aimed at them, not the generic queue.
4. The registry-document rows (Harley "Parts Listing", "Shop Dope/Service
   Bulletins", "Oper./Maint./Spec. Book" - 113 rows) are not vehicles and should
   be deleted from the catalog, not photographed.

---

## Cycle 3 - 2026-09-20, ~55 min (top-200 gap list x2, + per-make categories)

| | families | rows |
|---|---|---|
| overall | 3,897 -> **4,055** (+158) of 8,829 | 17,068 -> **18,577** (+1,509) of 30,513 |
| motorcycles | 3,325 -> **3,379** (+54) of 7,795 | 13,188 -> **13,469** (+281) of 24,135 |
| manual-bearing bikes | 1,710 -> **1,752** (+42) of 3,950 | 9,415 -> **9,648** (+233) of 15,878 |
| cars | 572 -> **676** (+104) of 1,034 | 3,880 -> **5,108** (+1,228) of 6,378 |

**113 new photos** (own tiles 279 -> 378), $0.17 of `images.score`, 68 MB of 150 MB.
`lookupImage` now resolves **19,639/30,578 rows (64.2%)**, up from 17,129 (61.7%)
when the gap doc was first written.

**The top-200 list is the whole game.** First pass over it: 199 models, **83
photos, 42% hit rate**. Compare the open queue in cycle 2: 4,413 models for 3
photos. That is a ~600x difference in yield per model walked, because the list is
sorted by catalog rows and because a model with many rows is a model Commons has
usually heard of. A second regenerated pass added 30 more (199 models, 15%) - the
list decays as it is worked, so regenerate between passes, which `--top N` now
does cheaply.

**Per-make `deepcategory:` works.** `deepcategory:"Kawasaki motorcycles" VULCAN
750` reaches files no filename query can - Commons files the uploader called
`Vn750-2.jpg`. First pass: **98/123 candidates passed the gate, 23 hits**; second
pass 10/25, 10 hits. It is now the second-best source after plain search. Guard
that matters: a deep-category hit proves nothing about *which* model, so the file
must also name the model in its description or categories - without that a VN700
walks in as a VN750.

**Tooling.** `web/tools/images-coverage.mjs` gained `--top N` (default 30) and
`--keys`, which prints bare `Make|Model` lines - and nothing else - so it pipes
straight into `images2.py --only`. It drops the Harley registry-document rows on
the way out.

**What is exhausted.** Unchanged from cycle 2, and now measured twice: the
dirt-bike head of the gap list (Prius aside: YZ85, YZ85LW, KX65, KX85, KX100,
KTM 50 SX, TT-R230, TT-R110E, 250 XC/XC-F/XC-W, TC 250, KLX300R) is the reason
the second pass opened with 40 models and zero hits. Those ~40 keys are in the
miss cache and should simply be **skipped by dropping `--retry-misses` on gap-list
runs** - using it there was my error this cycle and cost ~8 minutes.

**Next leads.**
1. Keep the loop: regenerate `--keys --top 200`, run it *without* `--retry-misses`,
   repeat. It is the only lane above 10% yield.
2. Cars are now 80.1% of rows and motorcycles 55.8%. The founder wants
   motorcycles, but the gap list is currently car-heavy because cars have more
   rows each. A `--kind bike` filter on the coverage tool would let a cycle spend
   the whole hour on the motorcycle gap list; that is the next thing to build.
3. `makecat` has only been run against the gap list. Running it across the open
   manual-bearing lane has not been tried and is the obvious next sweep.
