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
