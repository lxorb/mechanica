# Measured LLM cost — Mechanica (44521 logged calls)

Source: `C:\Users\me\trustthemanual\api\data\costs.jsonl` · `C:\Users\me\trustthemanual\api\data\mass_report.jsonl` · `C:\Users\me\trustthemanual\api\data\manuals` · live `/api/cost` + `/api/cost/ttc`

## 1. Baselines — the whole manual in the prompt, once per question

| manual | pages | prompt tokens | naive: gpt-6-astra | + prompt cache | reasonable: gpt-5.6-luna |
| --- | --- | --- | --- | --- | --- |
| KTM 390 Duke 2023 (demo) | 128 | 102,400 | $1.029 | $0.107 | $0.0206 |
| median manual in our catalog | 170 | 136,000 | $1.365 | $0.141 | $0.0273 |
| BMW R 12 G/S 2026 (demo) | 270 | 216,000 | $2.165 | $0.221 | $0.0433 |
| largest manual in our catalog | 775 | 620,000 (2x) | $12.405 | $1.245 | $0.2481 |
| the founder's 500-page workshop manual | 500 | 400,000 (2x) | $8.005 | $0.805 | $0.1601 |

`800` tokens/page and the >272,000-token 2x rule are `app/llm.py`. Output is 100 tokens at the model's output price. The cache column is the best case for the naive design, not the normal one: it needs the same manual re-asked inside the cache TTL.

Live `/api/cost` reports `naivePerAsk` **$12.40** for the biggest manual in the deployed catalog, over 2182 calls and $13.80 spent.

## 2. Ours — per operation, stitched from the call log

| operation | n | mean tokens in | cached | mean out | mean $ | median $ | total $ |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ask (router + picker) | 482 | 4,421 | 87.2% | 104 | $0.001943 | $0.001790 | $0.9367 |
| ask (router only) | 1619 | 3,400 | 99.8% | 50 | $0.000129 | $0.000130 | $0.2093 |
| chat | 248 | 5,803 | 76.8% | 154 | $0.004200 | $0.004327 | $1.0417 |
| identify.part:gpt-5.6-luna | 8 | 1,242 | 38.7% | 64 | $0.000239 | $0.000278 | $0.0019 |
| identify.part:gpt-6-astra | 3 | 1,283 | 0.0% | 24 | $0.014047 | $0.014360 | $0.0421 |
| identify.photo:gpt-5.6-luna | 115 | 1,898 | 22.6% | 334 | $0.000704 | $0.000696 | $0.0809 |
| identify.photo:gpt-6-astra | 8 | 1,254 | 0.0% | 242 | $0.024661 | $0.024455 | $0.1973 |

Stitch check: 2101 asks, 482 paid for a picker, 1619 did not (**77.1% of asks make zero picker calls**). Unstitched calls: 0 picker, 0 chat.

This log is every call ever made, development included, so its ask mix is picker-heavier than a rider's. The controlled 150-query eval (`api/eval/report.md`) is the honest per-ask number: **$0.00038 per ask**, 1.15 LLM calls per ask. Both are carried below.

Ingest, from `mass_report.jsonl`: 648 manuals, mean **$0.0951** (median $0.0972, max $0.1810) for a mean of 177 pages = $0.538 per 1,000 pages. Paid once per manual, never per question.

### Every call, by route and model

| route | model | calls | mean in | cached | mean out | $/call | $ total |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ask.picker | gpt-5.6-terra | 482 | 1,529 | 63.6% | 42 | $0.001809 | $0.8717 |
| ask.router | gpt-5.6-luna | 2,349 | 3,305 | 99.7% | 53 | $0.000131 | $0.3081 |
| chat.answer | gpt-5.6-terra | 248 | 2,314 | 42.7% | 101 | $0.004064 | $1.0079 |
| climate.extract | gpt-5.6-luna | 1,555 | 454 | 0.0% | 286 | $0.000434 | $0.6743 |
| identify.part | gpt-5.6-luna | 8 | 1,242 | 38.7% | 64 | $0.000239 | $0.0019 |
| identify.part | gpt-6-astra | 3 | 1,283 | 0.0% | 24 | $0.014047 | $0.0421 |
| identify.photo | gpt-5.6-luna | 115 | 1,898 | 22.6% | 334 | $0.000704 | $0.0809 |
| identify.photo | gpt-6-astra | 8 | 1,254 | 0.0% | 242 | $0.024661 | $0.1973 |
| illustrations | gpt-image-1 | 102 | 140 | 0.0% | 1,056 | $0.042240 | $4.3085 |
| images.score | gpt-5.6-luna | 8,681 | 844 | 2.5% | 309 | $0.000536 | $4.6497 |
| ingest.keywords | gpt-5.6-luna | 3,335 | 536 | 0.0% | 1,564 | $0.001984 | $6.6161 |
| ingest.struct | gpt-5.6-luna | 27,364 | 2,573 | 47.0% | 1,729 | $0.002372 | $64.9084 |
| offers | gpt-5.6-terra | 44 | 17,155 | 26.5% | 894 | $0.060959 | $2.6822 |
| offers.fast | gpt-5.6-luna | 33 | 13,114 | 35.6% | 621 | $0.021012 | $0.6934 |
| offers.fast.extract | gpt-5.6-luna | 6 | 663 | 0.0% | 48 | $0.000191 | $0.0011 |
| offers.probe | gpt-5.4-mini | 5 | 9,199 | 36.7% | 607 | $0.025351 | $0.1268 |
| offers.probe | gpt-5.6-luna | 11 | 13,079 | 29.1% | 511 | $0.020725 | $0.2280 |
| offers.probe | gpt-5.6-terra | 4 | 15,172 | 30.6% | 1,226 | $0.056693 | $0.2268 |
| probe.picker | gpt-5.6-terra | 48 | 1,922 | 75.8% | 32 | $0.001606 | $0.0771 |
| probe.pk2 | gpt-5.6-luna | 40 | 1,996 | 72.6% | 25 | $0.000168 | $0.0067 |
| probe.pk2 | gpt-5.6-terra | 40 | 1,996 | 82.1% | 27 | $0.001361 | $0.0544 |
| probe.router | gpt-5.6-luna | 16 | 2,959 | 83.7% | 51 | $0.000208 | $0.0033 |
| probe.router2 | gpt-5.6-luna | 24 | 3,487 | 99.8% | 48 | $0.000129 | $0.0031 |

## 3. The savings ladder

| rung | $ / ask | $ / chat answer | step | how it is computed |
| --- | --- | --- | --- | --- |
| 0 · naive: whole manual, flagship, every question | $1.3650 | $1.3650 | 1x | 170-page manual x 800 tok in gpt-6-astra |
| 1 · + prompt-cache the manual (best case for that design) | $0.1410 | $0.1410 | 10x | cached-input price, app/llm.py PRICES |
| 2 · page retrieval instead of whole manual (still flagship) | $0.04388 | $0.02821 | 48x (chat) | logged token counts re-priced at gpt-6-astra |
| 3 · + model tiering (luna router / terra picker + chat) | $0.001626 | $0.005845 | 4.8x vs rung 2 | same tokens, our models, cache ignored |
| 4 · + prompt caching + spec path + picker gating + compression | $0.000545 | $0.004200 | 1.4x vs rung 3 | what the log actually billed |
| 5 · + answer cache on a repeated question | $0.000000 | $0.000000 | ∞ | ask._cache / ttc._cache, `usd` forced to 0 |

### Rung detail, each measured separately

**The one controlled A/B** — the same 150 rider queries, before and after the router rewrite, the deterministic spec path and the picker gate (`api/eval/report-baseline.md` → `api/eval/report.md`):

|  | before | after | change |
| --- | --- | --- | --- |
| $ per ask | $0.00207 | $0.00038 | **5.4x cheaper** |
| LLM calls per ask | 1.73 | 1.15 | −34% |
| p95 latency | 4.99 s | 3.33 s | −33% |
| out-of-scope answered correctly | 55% | 100% | **+45 pts** |
| in-scope top-1 | 100% | 100% | unchanged |

Cheaper and more accurate on the same queries: the cheapest call is the one not made.

**Prompt caching** — cached tokens x (fresh price − cached price), per route:

| route | model | calls | cache hit rate | $ paid | $ saved | $ without cache |
| --- | --- | --- | --- | --- | --- | --- |
| ask.picker | gpt-5.6-terra | 482 | 63.6% | $0.8717 | $0.8430 | $1.7147 |
| ask.router | gpt-5.6-luna | 2,349 | 99.7% | $0.3081 | $1.3933 | $1.7014 |
| chat.answer | gpt-5.6-terra | 248 | 42.7% | $1.0079 | $0.4416 | $1.4494 |
| identify.part | gpt-5.6-luna | 8 | 38.7% | $0.0019 | $0.0007 | $0.0026 |
| identify.photo | gpt-5.6-luna | 115 | 22.6% | $0.0809 | $0.0089 | $0.0898 |
| images.score | gpt-5.6-luna | 8,681 | 2.5% | $4.6497 | $0.0332 | $4.6829 |
| ingest.struct | gpt-5.6-luna | 27,364 | 47.0% | $64.9084 | $5.9602 | $70.8686 |
| offers | gpt-5.6-terra | 44 | 26.5% | $2.6822 | $0.3597 | $3.0419 |
| offers.fast | gpt-5.6-luna | 33 | 35.6% | $0.6934 | $0.0277 | $0.7211 |
| offers.probe | gpt-5.4-mini | 5 | 36.7% | $0.1268 | $0.0114 | $0.1382 |
| offers.probe | gpt-5.6-luna | 11 | 29.1% | $0.2280 | $0.0075 | $0.2355 |
| offers.probe | gpt-5.6-terra | 4 | 30.6% | $0.2268 | $0.0335 | $0.2602 |
| probe.picker | gpt-5.6-terra | 48 | 75.8% | $0.0771 | $0.1258 | $0.2029 |
| probe.pk2 | gpt-5.6-luna | 40 | 72.6% | $0.0067 | $0.0104 | $0.0172 |
| probe.pk2 | gpt-5.6-terra | 40 | 82.1% | $0.0544 | $0.1180 | $0.1724 |
| probe.router | gpt-5.6-luna | 16 | 83.7% | $0.0033 | $0.0071 | $0.0105 |
| probe.router2 | gpt-5.6-luna | 24 | 99.8% | $0.0031 | $0.0150 | $0.0181 |

**Model tiering** — two routes were run on both a flagship and a cheap model against the same job:

| route | flagship | tier we ship | factor |
| --- | --- | --- | --- |
| identify.part | gpt-6-astra $0.014047 | gpt-5.6-luna $0.000239 | 59x |
| identify.photo | gpt-6-astra $0.024661 | gpt-5.6-luna $0.000704 | 35x |
| offers.probe | gpt-5.6-terra $0.056693 | gpt-5.6-luna $0.020725 | 3x |
| probe.pk2 | gpt-5.6-terra $0.001361 | gpt-5.6-luna $0.000168 | 8x |

**Referral stripping + bear-2 compression** — tokens removed before the prompt was ever billed:

- `api/eval/chat-report.md`: 46,501 tokens in → 31,977 out over 25 answers = **31.2% saved**, 581 tokens per answer.
- At gpt-5.6-terra fresh input ($2.00/M) that is **$0.00116 per answer**, **21.7%** of what a chat answer would otherwise cost ($0.00536 → $0.00420).
- `chat._strip_referrals` removes the dealer-referral boilerplate first: 2.8% of the KTM page text, 5.7% of the BMW (`api/docs/CHAT-RESEARCH.md`), with 368/368 and 256/256 printed figures intact.

- Live `/api/cost/ttc` is reachable and `enabled: True`, but this replica's counters are at zero - they are in-memory per replica and reset on restart. Ask one chat question against production and read it again.

**Deterministic spec path + picker gating** — the two levers that remove an LLM call entirely:

- `api/eval/report.md`: 172 LLM calls for 150 asks = 1.15 calls per ask, so **85.3% of asks never pay for a picker**.
- Over the whole log: 1619 of 2101 asks (**77.1%**) are router-only.
- A spec question (`how much oil does it take`) is answered from parsed spec rows plus BM25: zero LLM calls past the router (`app/ask.py::_by_spec`).
- A procedure question whose second BM25 hit is below `PICK_MARGIN` skips the picker too (`app/ask.py`, `decisive`).
- Retrieval itself is free: BM25 in process, `app/search/local.py`, no embeddings, no vector DB.

**On-demand ingest** — the cost that is paid once instead of per question:

- $0.0951 mean per manual over 648 real ingests, paid once. That is **7% of ONE naive question** ($1.36), and it then answers every question about that bike forever.
- Break-even against the naive stack: **0.07 questions**. Against the reasonable luna baseline ($0.0273): **4.1 questions**.

## 4. The mechanic's monthly bill — 40 questions/day x 30 days = 1,200 questions

| stack | $/q (170 p) | $/mo (170 p) | $/q (500 p) | $/mo (500 p) | questions per $1 (500 p) |
| --- | --- | --- | --- | --- | --- |
| naive, whole manual, flagship | $1.365000 | $1,638.00 | $8.005000 | $9,606.00 | 0.12 |
| naive + prompt cache (best case for that design) | $0.141000 | $169.20 | $0.805000 | $966.00 | 1 |
| reasonable, whole manual in gpt-5.6-luna | $0.027320 | $32.78 | $0.160120 | $192.14 | 6 |
| ours, every question a chat answer (worst case) | $0.004200 | $5.04 | $0.004200 | $5.04 | 238 |
| ours, every question an ask, whole-log mix | $0.000545 | $0.65 | $0.000545 | $0.65 | 1,833 |
| ours, every question an ask, 150-query eval mix | $0.000380 | $0.46 | $0.000380 | $0.46 | 2,632 |

Left pair: the median manual in our catalog (170 pages). Right pair: a 500-page workshop manual, the size behind the founder's "one question cost about $4". Our side does not move with page count, because the prompt never holds the manual - only the pages BM25 returned.

Plus ingest: one manual per bike that comes through the door, $0.0951 each, forever, not per question.

## 5. At 1,000 mechanics

| stack | questions / month | $ / month | $ / year |
| --- | --- | --- | --- |
| naive, whole manual, flagship (median manual) | 1,200,000 | $1,638,000 | $19,656,000 |
| ours, worst case: every question a chat answer | 1,200,000 | $5,040 | $60,485 |
| ours, the default path: an ask | 1,200,000 | $456 | $5,472 |

Plus the catalog: 543 manuals already ingested at $0.0951 each = $52 spent once, shared by every shop. Ingest does not scale with mechanics, it scales with distinct manuals, and there are only so many motorcycles.

