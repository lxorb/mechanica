# ask eval

2026-09-19 23:38 UTC · 150 queries · router gpt-5.6-luna · picker gpt-5.6-terra

## Gates

| gate | value | pass |
| --- | --- | --- |
| top-1 in-scope >= 95% | 100.0% | PASS |
| out-of-scope empty >= 90% | 100.0% | PASS |
| p95 latency <= 4 s | 3.33 s | PASS |
| mean cost per ask <= $0.002 | $0.00038 | PASS |
| AskResponse carries ids and scores only | 0 leaks | PASS |
| spec answers grounded | 0 ungrounded quotes | PASS |

## Accuracy by category

| category | n | top-1 | top-4 | empty | mean s | p95 s | mean $ |
| --- | --- | --- | --- | --- | --- | --- | --- |
| plain | 28 | 100.0% | 100.0% | 0.0% | 1.70 | 3.09 | $0.00050 |
| messy | 20 | 100.0% | 100.0% | 0.0% | 1.72 | 3.33 | $0.00030 |
| typo | 16 | 100.0% | 100.0% | 0.0% | 1.48 | 2.44 | $0.00023 |
| slang | 18 | 100.0% | 100.0% | 0.0% | 2.03 | 3.50 | $0.00090 |
| spec | 24 | 100.0% | 100.0% | 0.0% | 1.37 | 2.09 | $0.00014 |
| part | 14 | 100.0% | 100.0% | 0.0% | 1.87 | 2.80 | $0.00057 |
| oos | 20 | - | - | 100.0% | 1.21 | 1.96 | $0.00010 |
| nonen | 10 | 100.0% | 100.0% | 0.0% | 1.41 | 2.63 | $0.00045 |

In-scope top-1 100.0%, top-4 100.0% over 130 queries. In-scope answers that came back empty: 0.0%.
Out-of-scope false positives 0.0%.

## Latency and cost

- mean 1.60 s, p95 3.33 s (sequential, cold cache)
- cost log delta on ask.* routes $0.0577 over 150 asks = $0.00038 per ask ($0.7869 logged by other routes meanwhile)
- by route: ask.picker $0.0379, ask.router $0.0197
- LLM calls: 172 for 150 asks (1.15 per ask)

## Grounding (spec answers)

- spec rows on returned sections whose quote is not verbatim on its page: 0
- spec answers whose lead section has no parsed spec row (printed value not extracted): 2
  - unsourced: messy-20 'how worn can the tyres get before i have to change them' -> tyre-tread (no spec row parsed)
  - unsourced: typo-15 'treed depth' -> tyre-tread (no spec row parsed)

## Misses (0)

None.
