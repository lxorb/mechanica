# ask eval

2026-09-19 23:22 UTC · 150 queries · router gpt-5.6-luna · picker gpt-5.6-terra

## Gates

| gate | value | pass |
| --- | --- | --- |
| top-1 in-scope >= 95% | 100.0% | PASS |
| out-of-scope empty >= 90% | 55.0% | FAIL |
| p95 latency <= 4 s | 4.99 s | FAIL |
| mean cost per ask <= $0.002 | $0.00207 | FAIL |
| AskResponse carries ids and scores only | 0 leaks | PASS |
| spec answers grounded | 2 unbacked | FAIL |

## Accuracy by category

| category | n | top-1 | top-4 | empty | mean s | p95 s | mean $ |
| --- | --- | --- | --- | --- | --- | --- | --- |
| plain | 28 | 100.0% | 100.0% | 0.0% | 3.18 | 6.45 | $0.00248 |
| messy | 20 | 100.0% | 100.0% | 0.0% | 3.37 | 4.51 | $0.00291 |
| typo | 16 | 100.0% | 100.0% | 0.0% | 3.09 | 5.10 | $0.00225 |
| slang | 18 | 100.0% | 100.0% | 0.0% | 3.44 | 4.99 | $0.00291 |
| spec | 24 | 100.0% | 100.0% | 0.0% | 1.84 | 3.12 | $0.00026 |
| part | 14 | 100.0% | 100.0% | 0.0% | 3.28 | 4.40 | $0.00299 |
| oos | 20 | - | - | 55.0% | 2.16 | 3.39 | $0.00108 |
| nonen | 10 | 100.0% | 100.0% | 0.0% | 3.04 | 4.50 | $0.00249 |

In-scope top-1 100.0%, top-4 100.0% over 130 queries. In-scope answers that came back empty: 0.0%.
Out-of-scope false positives 45.0%.

## Latency and cost

- mean 2.88 s, p95 4.99 s (sequential, cold cache)
- cost log delta $0.3107 over 150 asks = $0.00207 per ask
- by route: ask.picker $0.2888, ask.router $0.0219
- LLM calls: 259 for 150 asks (1.73 per ask)

## Grounding (spec answers)

- spec sections returned without a verbatim spec quote on their page: 2
- spec rows in returned sections whose quote is not verbatim on its page: 0
  - unbacked: messy-20 'how worn can the tyres get before i have to change them' -> tyre-tread (no grounded spec row)
  - unbacked: typo-15 'treed depth' -> tyre-tread (no grounded spec row)

## Misses (9)

- `oos-02` ktm 'best exhaust' -> ['engine-oil-change', 'engine-torques', 'chassis-torques', 'tire-condition'] (expected [], intent part)
- `oos-07` ktm 'how much is this bike worth second hand' -> ['front-brake-fluid-level', 'battery-charge', 'fuses', 'coolant-level'] (expected [], intent unknown)
- `oos-08` ktm 'can i fit a turbo to it' -> ['headlight-range', 'fuses', 'engine-oil-change', 'battery-charge'] (expected [], intent part)
- `oos-10` ktm 'who won motogp last weekend' -> ['tire-pressure', 'tire-condition', 'chain-tension-check', 'battery-charge'] (expected [], intent unknown)
- `oos-11` bmw 'how do i wheelie' -> ['front-wheel-removal', 'engine-oil-level', 'spring-preload-front', 'td-wheels-tyres'] (expected [], intent unknown)
- `oos-12` bmw 'best exhaust for it' -> ['td-engine-oil', 'td-electrical', 'td-wheels-tyres', 'engine-oil-level'] (expected [], intent part)
- `oos-15` bmw 'what colour should i paint it' -> ['td-engine-oil', 'engine-oil-level'] (expected [], intent unknown)
- `oos-16` bmw 'get me an insurance quote' -> ['seat-removal'] (expected [], intent unknown)
- `oos-19` bmw 'play some music' -> ['seat-removal'] (expected [], intent unknown)
