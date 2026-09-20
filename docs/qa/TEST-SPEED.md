# TEST-SPEED — the backend suite, 2026-09-20

`api/.venv/Scripts/python -m pytest api/tests -q`

| | before | after |
| --- | --- | --- |
| whole suite | **1464 s** (24 min 24 s) | **48.6 s / 47.8 s** (two consecutive runs) |
| slowest test | 239.6 s | 1.3 s |
| result | 847 passed, 2 failed, 20 skipped | 876 passed, 20 skipped |

The two "before" failures were the `test_bughunt_ondemand` stall tests, which time real seconds and
lost the race to the other work on the box while the baseline ran. They pass in both "after" runs.
The test count rose because another agent checked in `tests/test_document_titles.py` in between;
nothing here adds, removes, skips or weakens a test.

The before run had to be taken with `--timeout=900`: at the committed 120 s per-test limit the suite
did not finish at all — `test_cost_route_reports_the_largest_manual` blew through it and pytest-timeout
killed the process.

## Top 10 durations

| | before | | after | |
| -- | --- | --: | --- | --: |
| 1 | `test_bughunt_store::test_cost_route_reports_the_largest_manual` | 239.6 s | `test_climate::test_every_antifreeze_floor_in_the_corpus_is_the_same_number` | 1.26 s |
| 2 | `test_dropbox_sync::test_status_route_reports_every_file_and_its_state` | 119.1 s | `test_bughunt_api::test_parts_catalog_route_still_answers` | 1.26 s |
| 3 | `test_bughunt_ondemand::test_head_answers_wherever_get_does[/cost]` | 110.0 s | `test_voice_latency::test_a_spoken_turn_reasons_at_none_and_a_typed_one_at_low` | 1.12 s |
| 4 | `test_dropbox_sync::test_a_changed_revision_is_ingested_again` | 95.9 s | `test_main::test_ask_returns_the_manuals_own_sections_in_the_pickers_order` | 1.00 s |
| 5 | `test_climate::test_every_antifreeze_floor_in_the_corpus_is_the_same_number` | 68.4 s | `test_main::test_ask_drops_unknown_picker_ids` | 0.99 s |
| 6 | `test_bughunt_ondemand::test_head_answers_wherever_get_does[/manuals]` | 65.3 s | `test_voice_latency::test_a_typed_ask_still_prices_itself_and_reads_the_log_once` | 0.99 s |
| 7 | `test_bughunt_api::test_parts_catalog_route_still_answers` | 52.2 s | `test_main::test_ask_router_failure_still_answers_from_the_index` | 0.99 s |
| 8 | `test_dropbox_sync::test_an_invalidated_cursor_is_thrown_away_and_the_folder_relisted` | 51.4 s | `test_ttc::test_any_bad_reply_falls_back_to_the_original_text[empty-output]` | 0.90 s |
| 9 | `test_dropbox_sync::test_first_pass_lists_downloads_and_ingests` | 51.2 s | `test_ttc::test_any_bad_reply_falls_back_to_the_original_text[grew]` | 0.90 s |
| 10 | `test_dropbox_sync::test_shop_copy_never_overwrites_the_free_owner_s_manual` | 50.4 s | `test_ttc::test_any_bad_reply_falls_back_to_the_original_text[http-500]` | 0.90 s |

`test_manuals_list`, the test that prompted this, went from 116.7 s to 0.08 s; `test_cost_shape`
from 6.7 s (in a run whose `/manuals` cost had already been paid by an earlier test) to 0.04 s.

## Where the time was

Nothing was sleeping and nothing touched the network. Measured on this box, cold:

| read | cost |
| --- | --- |
| `FileStore.manuals()` — 508 documents, 62 MB | 0.8 s read + 22.7 s `json.loads` + 34.4 s validate = **58 s** |
| `FileStore.costs()` — 44 061 events | 0.8 s + 16.7 s = **17.5 s** |
| `_registry_rows()` — 99 313 rows, 39 MB | 3.7 s + 8.9 s = **12.6 s** |
| `FileStore.bikes()` — 30 578 rows | **0.8 s**, and `GET /catalog` then re-validates and serialises all of them |
| the conftest seed | `copytree` of **4.5 GB**, 4.1 GB of it PDFs nothing reads |

Three things multiplied that. `GET /manuals` calls `manuals()`; `GET /cost` calls `costs()` *and*
`max_manual_pages()`, which falls back to `manuals()` on a FileStore. Nothing was cached across
calls, because `conftest.clean_caches` drops the module-level store before every test, so each test
built a fresh `FileStore` and re-read the corpus from scratch. And the suite pointed at a full copy
of `api/data` — the deployed corpus — where three manuals would have said the same thing.

## What changed

**`api/app/store.py`** — a process-wide read cache for `manuals()`, `manual()`, `bikes()`, `costs()`
and the registry rows, keyed on `(root, kind) -> (stamp, value)`. The stamp is the filesystem
fingerprint of the file(s) behind the read — for `manuals/` a `(name, mtime_ns, size)` row per file,
so a rewrite, a new file and a deletion all show — plus a write counter the module bumps on every
write it makes, because Windows can stamp two writes inside one clock tick with the same mtime.
Either half changing re-reads. Entries are bounded per family, so a long-lived replica cannot grow
without end. This replaces the per-instance `_registry_cache`, which a new `FileStore` threw away.

What is cached is the **parsed JSON, not the models built from it**. `test_store.py` states outright
that a store hands back objects the caller owns (`put_bikes`, mutate what `bike()` returned, read it
back unchanged), so every call still validates its own. `_registry_rows` stays the one documented
exception — validating 99k rows is the expensive half there and no caller owns a row.

No route, no signature and no return value changed.

**`api/tests/conftest.py`** — the seed is now selective:

- the four per-manual directories (`manuals/ pages/ specs/ pdf/`) carry five manual ids instead of
  509: the two the tests name, the two with seeded offers, and the 381-page Africa Twin, which is
  what pins `max_manual_pages()` and therefore the `/cost` naive-per-ask figure the shape test
  compares against. 4.5 GB copied becomes ~90 MB.
- `bikes.json` keeps every vehicle a manual points at plus one per `(make, kind)` — 30 578 rows to
  705. One-per-make is exactly what `dropbox_sync._makes()` derives from the catalogue as a whole,
  so the "a file we cannot place is reported, not guessed" test sees the same make set it did.
- `costs.jsonl` keeps its last 2000 events. Same shape, and the same claim the shape test makes:
  `naivePerAsk` 6.096 still dwarfs `total/asks` (0.0035).
- `registry.json` keeps its first 5000 rows. Two tests read the seeded registry: one asserts the
  route answers with a list, the other reads `registry()[:50]` and the host set — and the head of
  the file is kept verbatim. `registry-fragments/`, which is what `test_cars_registry` validates,
  is seeded whole, as is `climate/`, whose 527-file rulebook the corpus-wide climate test counts.

Every test that iterates data was checked against the trim: they iterate `(KTM, BMW)`, the climate
rulebook, or a `tmp_path` store they wrote themselves. Nothing counts manuals or vehicles.

**`api/pytest.ini`** — per-test timeout 120 s → 30 s. Still 15x the slowest test plus a minute of
cold imports, and a test that goes back to reading the corpus per call now fails rather than passes
slowly.
