# Mechanica pitch brief (shared by every pitch agent)

Product: pick your vehicle (search, photo, or VIN) -> the official manual opens on the exact page, lines marked ->
3D model explodes and highlights the part -> full manual -> exact-fit parts with live prices -> grounded chat + voice.
Live: https://mechanica.emilvinu.ch  API: same origin /api. Repo: C:\Users\me\trustthemanual (read DESIGN.md, docs/ARCHITECTURE.md, docs/PITCH.md, web/QA.md, api/eval/*.md, api/docs/*.md, web/docs/*.md for verified numbers).

The story (true, from the founder): a friend in Germany started his own motorcycle workshop a few years ago.
He spends about 20% of his working time searching manuals instead of working on the bike. He does not use AI:
he does not trust it (95% right is not enough when he is liable for the 5%), and when he tried, one question cost
~$4 in API usage because the model had to read a 500-page manual, so he hit limits constantly.
Mechanica makes the manual the answer (never AI prose), finds the page in seconds, and costs a fraction of a cent.

## Numbers to reuse

**Every figure lives in `docs/pitches/numbers.md`** — generated, never typed, by
`api/.venv/Scripts/python tools/pitch_numbers.py --live --md ../docs/pitches/numbers.md` (run from `api/`).
Do not quote a number that is not in that file, and do not edit that file by hand: re-run the script.
It marks each value **measured / computed / assumed**, prints the exact definition next to it, and ends with
a generated discrepancy list — every figure in every pitch that contradicts it, with `file:line`.

Read its §11 before you write a sentence: three words have two honest counts each, and mixing them is how
nine pitches ended up with nine answers. *manuals we can reach* (14,865 distinct PDFs) is not *vehicles with
a manual* (18,564) — and 4,643 of those 18,564 are a non-English fallback, 25 a PDF we rendered ourselves. *mislabelled rows* is 6,244 owner-typed or 1,507 free-English — different questions.
*naive $/question* is $12.40 (largest deployed manual) or $1.36 (median), and the friend's ~$4 is neither.

**The ten to memorise** (2026-09-20; re-run before you present):

| number | say it as | definition |
|---|---|---|
| **30,409** | vehicles you can pick | rows in `GET /api/catalog` |
| **18,564** | with a free official manual | catalog rows carrying a `manualUrl` — **4,643** of them in another language, because no English manual exists for that vehicle |
| **99,338 / 84** | registry rows, publisher portals | rows in `registry.json`; distinct `site` |
| **14,865** | distinct free English PDFs | distinct URLs of ingestable rows |
| **543** | manuals already indexed | rows in `GET /api/manuals` |
| **69.5%** | catalog rows that show a photo | `docs/qa/images-gaps.md`, via `lookupImage` |
| **40.4 s / $0.095** | a cold manual becomes searchable | timed ingest; mean over 648 ingests |
| **$0.00038** | our cost per question | eval cost-log delta over 150 |
| **$12.40** | naive cost per question | `naive_usd(775)`, largest deployed manual |
| **100% / 0 of 20** | right section first; off-topic refused | eval: 130 in-scope, 20 off-topic |
| **100% / 0** | chat claims cited; invented numbers | 48 claim sentences, 43 quotes verbatim |

**His numbers, never ours — always say "he says":** ~20% of his working time (≈400 h/year, EUR 36k–48k of
billable time), ~$4 a question when he tried an LLM, "95% right isn't enough when I sign for the 5%."

Rules for every pitch: 5 minutes total; only mention what is relevant to THAT sponsor; concrete numbers with sources;
a flowchart (mermaid) of the architecture slice that matters to that sponsor; the demo moments and exact inputs;
what the judge should feel at each minute; a Q&A section with hard questions and honest answers; no marketing fluff.
Write to docs/pitches/<sponsor>.md. Screens/diagrams to docs/pitches/<sponsor>/.
