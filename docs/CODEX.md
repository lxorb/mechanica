# OpenAI Codex as the fifth teammate

Codex CLI 0.155.1 (`gpt-6-astra`, API-key auth) wrote three of the sixteen test modules in
`api/tests/` - 194 of the suite's 617 passing tests:
`npx @openai/codex exec -s workspace-write --skip-git-repo-check "<p>" < /dev/null`

- [run-1.md](codex/run-1.md) - `api/tests/test_store.py`, 29 tests, 69k tokens, ~2 min
- [run-2.md](codex/run-2.md) - `api/tests/test_local_index.py`, 100 tests, 63k tokens, ~8 min
- [run-3.md](codex/run-3.md) - `api/tests/test_llm.py`, **65 tests, 56,334 tokens, 2 min 02 s**, green on the
  first and only pytest run, nothing xfailed and not a line of `app/llm.py` touched. It pins the arithmetic
  behind every USD figure on the slides: `usd()` subtracting cached tokens exactly once and clamping at
  zero, eleven hard-coded per-model price literals, the `naive_usd()` discontinuity at the 272,000-token
  long-context boundary (340 p = $2.72, 341 p = $5.456) that produces the **$12.40** baseline, the $10/1k
  web-search fee, and `prompt_cache_key` pinned to `route:model`. Two honest caveats: it silently swapped
  the `fresh_store` fixture the prompt named for its own in-memory one, and "every model in `PRICES`"
  became five of the ten - all three models we quote are covered, the five unused ones are not.

Each log holds the exact prompt, the full stdout and what I fixed. The other thirteen modules are mine.

**The concrete improvement it delivered: it found a live search bug.** Run 2 mocked
`bm25.get_scores` and wrote a test pinning *where* the `FLOOR` gate in `app/search/local.py` sat -
on the raw BM25 peak, **before** the keyword and title bonuses. I had only a symptom:
`LocalIndex.query(ktm, ["torque"])` had started returning nothing. That test made it a diagnosis
in one read: "torque" is printed in almost every section, so its IDF collapses to ~0, the peak
never reaches `FLOOR = 1.2`, and the exact keyword hit on "tightening torque" never got to vote.
Same for "rear wheel" (peak 1.12). Reported; the search agent changed the gate to
`peak < FLOOR and not evidence`. All ten bare rider queries now rank their printed section first,
and the test is inverted to pin the new contract: a router's component guess never rescues a
query, only words the manual actually prints do.

**What it cost.** `--full-auto` is gone in 0.155.1 and, without `< /dev/null`, `codex exec` blocks
forever on "Reading additional input from stdin": two wasted restarts. Its sandbox redirects
`TMPDIR`, so run 1 was green for Codex and 28/29 errors for me. In run 2 it silently swapped easier
queries for the ten the prompt named, then reported success. Useful teammate, still needs reading.
