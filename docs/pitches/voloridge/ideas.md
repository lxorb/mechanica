# Voloridge "Signal in the Noise" — candidate features, scored

Scored 1–5 on Voloridge's four published criteria (Originality · Technical Excellence · Insight ·
Execution) plus a feasibility estimate in build-hours. Anything on Voloridge's own curated list is
marked **[curated]**; the challenge PDF says other datasets are allowed "if you stop by the booth",
but a curated one is a free point with the judges.

Voloridge's curated list (from the challenge PDF, fetched 2026-09-20):
NOAA ISD · OpenAlex · GDELT · NYC TLC · OpenAQ · PUDL · Materials Project.
Helper bucket: `s3://voloridge-hack-mit-2026/src/{dataset}/{README.md,fetch.py}`.

| # | idea | datasets | Orig | Tech | Insight | Exec | hrs | verdict |
|---|---|---|:--:|:--:|:--:|:--:|:--:|---|
| 1 | **Climate Fit** — extract every environment-conditional rule the manuals print (antifreeze floor, temperature-banded oil grade, "service more often in dusty conditions", salt-corrosion washdown), then resolve each one against the actual climate where the vehicle lives | **[curated]** NOAA ISD + OpenAQ + our 532-manual corpus | 5 | 5 | 5 | 4 | 4.0 | **PICK** |
| 2 | **Rulebook anomalies** — same extraction, compared *across* 532 manuals, 9 makes, 9 markets and 2024–2026 model years: who disagrees, who never updates, which number is copy-pasted worldwide | our corpus (+ NOAA to say who it hurts) | 5 | 4 | 5 | 5 | 1.5 | **PICK** (shares artefact with #1) |
| 3 | NHTSA complaints + recalls → "known failure signals for this part", NLP component classifier joined to the catalog | NHTSA (**not** curated) | 4 | 5 | 4 | 3 | 7+ | cut: off-list, and the fuzzy make/model/year join to 27,751 vehicles plus a component classifier is the whole build on its own |
| 4 | The registry as a dataset problem — 53,557 rows, 84 hosts, 28,200 distinct URLs, content-hash dedupe, brochure-vs-manual classification, retraction | ours | 4 | 5 | 3 | 5 | 0 | **already built** — use it as the narrative spine of the data half, not as a new build |
| 5 | Parts-offer price distributions as a live market dataset | retailer offers (not curated) | 3 | 3 | 3 | 3 | 3.0 | cut: not curated, thin n, and scraped prices are the weakest data we hold |
| 6 | NYC TLC duty-cycle model — turn trip records into a km/year distribution for urban commercial vehicles, then express every manual service interval in *days* for that duty cycle | **[curated]** NYC TLC | 4 | 3 | 3 | 4 | 2.5 | strong fallback; cute but a weaker safety story than #1 |
| 7 | GDELT defect-news signal per make/model | **[curated]** GDELT | 3 | 3 | 3 | 2 | 3.0 | cut: news is prose, and our product rule is "never AI prose, the manual is the answer" |
| 8 | OpenAlex → tribology/lubricant literature behind each spec | **[curated]** OpenAlex | 2 | 2 | 2 | 3 | 2.0 | cut: a mechanic does not want a citation to a journal |
| 9 | Materials Project → corrosion risk by part material | **[curated]** Materials Project | 3 | 3 | 2 | 2 | 4.0 | cut: our parts taxonomy has no material field; the join would be invented |
| 10 | PUDL → grid/EV charging context | **[curated]** PUDL | 2 | 2 | 2 | 3 | 2.5 | cut: no honest join to a manual |
| 11 | ISD wind/visibility → riding-condition windows | **[curated]** NOAA ISD | 2 | 2 | 2 | 4 | 1.5 | cut: a weather app, not a workshop tool |
| 12 | Freeze–thaw + salt-clause corrosion index | **[curated]** NOAA ISD | 4 | 4 | 4 | 4 | — | folded into #1 as one rule type |

## Why #1 + #2 win

**Originality.** Nobody has joined OEM handbook text to 600 GB of hourly weather observations. The
manuals themselves invite it and never close the loop: they print a threshold and leave the reader to
guess whether it applies. 522 of our 529 locally-stored manuals (98.7%) contain at least one
environment-conditional clause, and not one of them knows where the vehicle is.

**Technical Excellence.** Three hard, different problems in one pipeline: fixed-width binary-ish
parsing of a 600 GB archive reduced to ~4 MB; grounded clause→typed-rule extraction over 95,365
pages where a hallucinated threshold is a safety bug; and two geospatial joins (lat/lon → 12,774
active stations, station ↔ OpenAQ location ≤ 25 km).

**Insight.** Already measured before writing a line of the feature (see `spec.md` §7): **every one of
the 206 manuals in our corpus that prints an antifreeze floor prints the same number, −25 °C — across
9 markets including US, CA-adjacent, JP, CN, BR, AR, PH.** A random sample of 217 ISD stations that
report into 2025 says **22.6% of them went below that in 2024 alone.** One European number, shipped
worldwide, wrong for roughly a fifth of the planet's weather stations.

**Execution.** It lands on a screen we already have (Book/Parts), in the shape the product already
uses: a claim, a page number, and the manual's own line highlighted. No new UI paradigm, no prose.

**Why the two together.** #2 is free once #1's extractor exists — the same `ClimateRule[]` artefact,
grouped by rule type instead of by vehicle. #1 is the tool, #2 is the discovery. Voloridge asked for
both ("Great engineers build systems that can process data at scale. Great researchers discover
patterns hidden inside it. This challenge is about both.").

## What we deliberately do not claim

- Not a maintenance-prediction model. We surface the manufacturer's own printed rule and the measured
  climate; we never invent an interval.
- No causal claim. "22.6% of sampled stations breached the printed floor" is an exposure statistic,
  not a failure rate. We have no failure data and we say so.
- Station sample is station-weighted, not vehicle-weighted or population-weighted. ISD is dense in
  the US, Russia and Canada and thin in Africa. Stated in the Q&A, not hidden.
