# The nine pitches — index

One product, nine rooms. Every pitch is 5 minutes, tells the **same** story of the same friend's workshop,
and quotes the **same** numbers. Two files sit above all nine:

- **[`numbers.md`](numbers.md)** — generated, never typed. 72 figures with their exact definitions, each
  marked *measured / computed / assumed*, §11 for the words that have two honest counts, and a generated
  discrepancy list of every figure in these files that contradicts it. Regenerate and fix to zero before
  you present:
  `cd api && .venv/Scripts/python tools/pitch_numbers.py --live --md ../docs/pitches/numbers.md`
- **[`BRIEF.md`](BRIEF.md)** — **the ten numbers to memorise**, and the shared story in five sentences.

**The story, identical in all nine.** A friend opened his own motorcycle workshop in Germany a few years
ago. He says about **20%** of his working time goes to looking for the right page — roughly **400 hours** a
year. He does not use AI, for two reasons he gave himself: it is right 95% of the time and he is liable for
the 5%, and when he tried it one question cost about **$4** because the model had to read a 500-page manual,
so he hit usage limits constantly. Say "he says" every time. His ~$4 is **his** bill on **his** manual; our
own measured naive worst case is **$12.40** and our median is **$1.36** — three different numbers, never
blended.

**The demo bike, identical in all nine** unless the pitch says why not: **KTM 390 Duke 2024**
(`ktm-390-duke-2024-om-en`), warm, **143 pages**, a hand-curated 20-section index so every scripted question
lands. `chain is loose` → *Checking the chain tension* **p.77–78** + *Adjusting the chain tension* **p.78**.
`front axle nut torque` → *Chassis tightening torques* **p.128–130**, printed figure **45 Nm**.

---

## The index

| # | pitch | target, and the angle | the demo moment |
|---|---|---|---|
| 1 | [`general.md`](general.md) | **Main track.** No tech words: a real mechanic, a real page. | Page 77 appears with the two answering lines marked — "the marker is only there because we found that exact text in KTM's PDF." |
| 2 | [`long-lake.md`](long-lake.md) | **Long Lake** — AI into an unglamorous service business. Cycle time, error rate and unit cost against a named baseline; the second deployment costs $0.095 and 40 s. | Five minutes of thumbing a PDF becomes two seconds — then naming our own weakest column (one design partner, zero installs) in minute 4 instead of losing it in Q&A. |
| 3 | [`openai.md`](openai.md) | **OpenAI** — ten API capabilities, each followed by our code that can throw its answer away. Codex as the fifth teammate. | The architecture flowchart: orange is an API call, green is the guardrail that discards it. Then the FLOOR bug Codex found. |
| 4 | [`token-company.md`](token-company.md) | **The Token Company** — the AI was never not-good-enough for this mechanic, it was too expensive. A savings ladder re-pricing the same measured tokens. | `/api/cost/ttc` moving live while the citation stays verbatim — a cost lever that can never become a correctness lever. |
| 5 | [`ramp.md`](ramp.md) | **Ramp** — EUR 24,640 a year lost to looking for a page, and cents a month to give it back. Every cell regenerable from `ramp/numbers.py`. | Cutting our own EUR 44,000 headline down to EUR 24,640 on stage, out loud, before anyone else does. |
| 6 | [`deepgram.md`](deepgram.md) | **Deepgram** — **live**. Four grounded tools are the agent's whole vocabulary; Deepgram calls our API server-to-server so the manual never enters the tab. | "And the front one?" → *forty five newton metres*, with page 130 turning itself mid-sentence. |
| 7 | [`elevenlabs.md`](elevenlabs.md) | **ElevenLabs** — agentic depth, latency, multimodal. Same grounding policy as Deepgram, imported not copied, with a test that fails if they drift. **Built, needs a key.** | The agent saying "this manual doesn't print a valve clearance" instead of supplying one. |
| 8 | [`dropbox.md`](dropbox.md) | **Dropbox** — owner's manuals are free, the service manual a shop needs is metered, so we index the copy the shop already bought. | A bike with no free manual answering a question sixty seconds after a PDF appeared in a folder — and an oddly-named file coming back `unmatched` instead of guessed at. |
| 9 | [`voloridge.md`](voloridge.md) | **Voloridge** — signal in the noise. The manual's own printed rules resolved against 600 GB of NOAA weather reduced in-stream to 4 MB. | Switching the location from Zurich to International Falls: the coolant row flips to *breached*, and tapping it lands on the page KTM printed. |

---

## The order to rehearse them in

1. **`general.md` first, always.** It is the spine — the opening, the demo taps and the Q&A that every other
   pitch reuses. Get this one muscle-memory and eight of the nine are 80% rehearsed.
2. **`long-lake.md`** next. Same story, hardest room, and it is the one that forces you to say the weakness
   out loud. If you can do this one you can do any of them.
3. **`openai.md`** — the only one where you talk over a diagram for 90 seconds. Rehearse the pointing.
4. **`token-company.md`**, then **`ramp.md`** — the two money pitches. Back to back, because they share the
   arithmetic and mixing their definitions is the classic failure.
5. **`deepgram.md`**, then **`elevenlabs.md`** — the two voice pitches, in that order: Deepgram is live and
   ElevenLabs reuses its policy and its fallback plan.
6. **`dropbox.md`**, then **`voloridge.md`** — the two most standalone. Voloridge last: it is the only pitch
   whose 5 minutes are mostly not the core product.

**Before any of them:** re-run `pitch_numbers.py` and read §11 of `numbers.md`. Nine pitches once had nine
answers because three words have two honest counts each.

---

## Do not say — per pitch

These are claims that would be **false today**. Check this list the morning of.

**All nine, global**

- ElevenLabs voice is **never** "live" — `GET /api/voice/config` returns `elevenlabsAgentId: null`. Say
  "built, one key away." The live voice you demo is **Deepgram**, and `deepgram: true`.
- The 3D backdrop is a **technical grid**. Do not show, promise or describe a panorama or a photographic
  workshop scene — there is none.
- **Dropbox folder sync** and **Climate Fit** are "built, deploying", not deployed features: `/api/dropbox/*`
  is not in the live OpenAPI, and `/api/climate/fit` answers `no climatology` on the replica.
- Never quote a **running ledger total** without the date beside it. `GET /api/cost` moved from $13.80 to
  $13.80 in thirteen minutes on the day these files were written. Prefer not quoting it.
- Never call **18,564** "manuals" — it is *vehicles carrying a free manual*. Distinct fetchable PDFs is
  **14,865**. And **4,643** of those 18,564 are an official manual in **another language** (Japanese mostly)
  because no English one exists for that vehicle — never present them as English manuals; **25** rows point at
  a PDF **we rendered** from Lexus's web-only manual, which is their text but not literally their file. Never call **6,244** and **1,507** the same number: owner-typed over every row vs the
  free-English subset.
- There is **no checkout**. "Live prices", never "buy".

**1 · general.md** — Do not say 17,556 manuals, or "seventeen thousand". Do not promise full offline: the
app, the vehicle list, the chapters and pages you already opened work with the network off; fetching a new
manual, chat and voice do not. Do not say "none of our service manuals are free" — 182 service rows, 15 of
them paid, subscription or dealer-login only.

**2 · long-lake.md** — Do not claim installs, adoption or throughput data: there is one design partner and
zero installs, and that is the deduction you name yourself. Do not quote a TAM; we have no sourced one. Do
not lead with a multiple — lead with $12.40 and $0.0006 and let them divide. Do not demo anything pending a
key, and do not say the word Elastic.

**3 · openai.md** — Do not say $6.096 or $6.10, 16,000×, 762 pages, 8,319 manuals, 332 warm manuals, or
$79.91/36,620 calls: all superseded. Do not say Elastic is running (`ES_URL` is unset and it has never been
run against a live cluster), that we use the Batch API, Assistants, embeddings in the live path, or any
fine-tune. `llm.embed()` exists and is unused — say so.

**4 · token-company.md** — Do not quote the live `/cost/ttc` percentage as the headline: it is in-memory
**per replica** and zeroes on restart, so a low number means a fresh replica, not a worse compressor. Quote
the **31.2%** eval figure and name it. Do not say 31.4%. Do not blend his ~$4 with our $12.40 — they are
different measurements of different manuals. Do not state what bear-2 costs us: there is no public $/M, we
log it as $0 and count tokens instead.

**5 · ramp.md** — Do not say EUR 44,000 without immediately taking the recovery and utilisation deductions
down to EUR 24,640. Do not present his 20%, the 2,000-hour year, or lookups-per-day as measured — they are
his number and our assumptions, and lookups/day is the one with no source at all. Do not quote a live
ledger total without the timestamp.

**6 · deepgram.md** — Do not claim keyterm prompting improves accuracy: A/B'd against shop noise it was
11.4% vs 13.6% WER at 3 dB and 14.1% vs 13.3% at 0 dB — that is noise, and the honest line is "it is the
documented lever, it costs nothing and it protects the proper nouns." Do not quote 2 s for a **procedure**
question: a spec question is ~2 s, a procedure question is **9.9 s**. Do not say the key is in the browser —
the Cloudflare Worker holds it. Do not say voice works offline; it is a cloud socket.

**7 · elevenlabs.md** — Do not imply any of it has run: there is no key on the machine, nothing in §2 has
touched a live ElevenLabs account, and `elevenlabs/chat-ui.patch` is **not applied**. Do not quote an
end-to-end ElevenLabs latency as measured — quote their published ~150 ms partial / ~75 ms first audio as
*theirs*, and our own tool leg from `GET /api/voice/elevenlabs/timings`. If the key does not exist on the
day, run the demo on Deepgram and say "same policy, same tools, one key away" — never mime a session that
did not happen.

**8 · dropbox.md** — Do not say the folder sync is connected: it is built, tested against a mocked Dropbox
and deploying. Do not demo the Chooser — it needs `TTM_DROPBOX_APP_KEY` and the button hides itself. Do not
say we host or re-publish manufacturer PDFs, and do not promise customer-facing shared links. Do not say
cross-tenant dedupe exists — the content hash is stored, the dedupe is not built.

**9 · voloridge.md** — Do not say Climate Fit is deployed and working: the routes are live, the climatology
is not in the replica. Do not say "22.9% of riders" — it is 22.9% of actively reporting weather stations,
and the station sample is biased toward the US, Russia and Canada. Do not imply we swept all 600 GB; say
which slice ran. Do not quote the † numbers (the hand-labelled precision/recall) as measured. Do not claim a
failure rate from running the wrong coolant — we have exposure data, not outcome data.
