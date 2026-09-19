# OpenAI Codex as the fifth teammate

Codex CLI 0.155.1 (`gpt-6-astra`, API-key auth) wrote two of the five test modules in
`api/tests/`: `npx @openai/codex exec -s workspace-write --skip-git-repo-check "<p>" < /dev/null`

- [run-1.md](codex/run-1.md) - `api/tests/test_store.py`, 29 tests, 69k tokens, ~2 min
- [run-2.md](codex/run-2.md) - `api/tests/test_local_index.py`, 100 tests, 63k tokens, ~8 min

Each log holds the exact prompt, the full stdout and what I fixed. The other three are mine.

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
