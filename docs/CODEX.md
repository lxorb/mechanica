# OpenAI Codex as the fifth teammate

Codex CLI 0.155.1 (`gpt-6-astra`, API-key auth) wrote two of the five test modules in
`api/tests/`: `npx @openai/codex exec -s workspace-write --skip-git-repo-check "<p>" < /dev/null`

- [run-1.md](codex/run-1.md) - `api/tests/test_store.py`, 29 tests, 69k tokens, ~2 min
- [run-2.md](codex/run-2.md) - `api/tests/test_local_index.py`, 100 tests, 63k tokens, ~8 min

Each log holds the exact prompt, the full stdout and what I fixed. The other three are mine.

**The concrete improvement it delivered.** Run 2 mocked `bm25.get_scores` and wrote
`test_confidence_floor_uses_bm25_before_ranking_bonuses`, which pins *where* the `FLOOR` gate in
`app/search/local.py` sits: it reads the raw BM25 peak and returns `[]` **before** the keyword and
title bonuses are added. I had a symptom - `LocalIndex.query(ktm, ["torque"])` had started
returning nothing - and that test made it a diagnosis in one read: "torque" is printed in almost
every section, its IDF collapses to ~0, the peak never reaches `FLOOR = 1.2`, and the exact keyword
hit on "tightening torque" never gets to vote. Same for "rear wheel" (peak 1.12). Both are now
`xfail` with that cause written out, and a companion test proves the router's rephrasings still
rank first, so the search agent sees what to fix and what not to break.

**What it cost.** `--full-auto` is gone in 0.155.1 and, without `< /dev/null`, `codex exec` blocks
forever on "Reading additional input from stdin": two wasted restarts. Its sandbox redirects
`TMPDIR`, so run 1 was green for Codex and 28/29 errors for me. In run 2 it silently swapped
easier queries for the ten the prompt named, then reported success. Useful teammate, still needs
reading.
