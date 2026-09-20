# Voice improvements — what a Deepgram judge would notice, scored

Scored for **a mechanic with the bike on the lift**, not for a demo. Impact 1–5. Build is wall-clock for
one engineer who already knows this codebase. Everything marked **shipped** was built and measured on
2026-09-20; everything else is honest backlog with a reason it is not done.

| # | improvement | impact | build | status |
|---|---|---|---|---|
| 1 | **Keyterm prompting from the manual's own vocabulary** — `agent.listen.provider.keyterms`, 100 phrases per bike built from part names, printed spec names, section headings, the rider phrasings each section was indexed under, then the standard parts catalogue spread one group at a time | **4** in principle, **unproven** in measurement | 2 h | **shipped** (`voice.py::_keyterms`) |
| 2 | **Saying a page is showing it** — the page number in the agent's own `ConversationText` moves the reader, because the model does not reliably call `show_page` (measured: 7 turns, 6 pages named, 0 calls) | **5** — this is the product's entire promise, and it was silently not happening | 45 min | **shipped** (`voice-deepgram.js`) |
| 3 | **Side- and kind-aware `get_spec`** — "and the **front** one?" drops every row printing the other end; "…**torque**" ranks `kind: torque` above a tyre pressure that shares the word "front". Live, before: four tyre pressures ranked above the 45 Nm the question wanted | **4** — the follow-up question is the one voice is *for*, and it was the one most likely to mislead | 1 h | **shipped** (`voice.py::_rank`) |
| 4 | **`find_procedure` returns the section's printed text** — collapse `find_procedure` + 4 × `read_page` into one call | **5** on latency: turn 4 goes from **9.9 s to ~3 s**, and it is 85% of our worst case | 3–4 h | not done — it changes `api/app/ask.py`, owned by another agent this sprint |
| 5 | **Speak the page first, then the figure** — "Page 78: one hundred newton metres" instead of "…is one hundred newton metres, page 78" | 3 — the reader turns ~1.5 s earlier, and the mechanic's eye gets there before the number does | 15 min (prompt) | not done — wants an A/B with a real mechanic, not a guess |
| 6 | **Confirmation before a dangerous procedure** — brake, fuel, airbag/pyro and anything the manual prints a `Warning` block for: the agent reads the manual's own warning sentence and waits for "go ahead" before the steps | **4** for liability, which is the whole reason this customer refused AI | 2 h — the ingest already keeps the warning blocks; needs a `kind` on the section and one prompt rule | not done |
| 7 | **Both units, always** — the KTM prints `100 Nm (73.8 lbf ft)` and our index stores them as two rows; the agent should say the shop's unit and offer the other, instead of picking whichever row ranked first | 3 — a US shop hearing "one hundred newton metres" has to convert in their head over a torque wrench | 1 h — pair the rows by `quote` and add a session unit preference | not done |
| 8 | **Numbers normalised server-side** — return `"one hundred newton metres"` next to `"100 Nm"` in the tool result, so correct speech is data rather than an instruction the model may drop | 3 — today it is a prompt rule and it holds, but a prompt rule is not a guarantee | 1.5 h | not done — measured 8/8 turns spoke figures correctly, so the rule is holding; revisit if it slips |
| 9 | **German, and accents** — `flux-general-multi` for listen, a multilingual aura-2 voice, `agent.language` (already a field we build) | **5** for the actual customer, who is German | ~1 week — the blocker is not Deepgram, it is indexing a German manual so the tool results come back in German | not done, and we will not fake it |
| 10 | **Workshop-noise measurement with real audio** — record a real shop at real SNR and re-run the keyterm A/B | 4 — it converts our weakest claim into a real one | 1 day + a shop | not done; this is the first thing a Deepgram credit would buy |
| 11 | **"What page am I on?"** — push the reader's current page into the session as context when the mechanic scrolls, so "read me this" works | 3 | 1 h | not done — needs a `chat-ui.js` hook, not owned by this agent |
| 12 | **Always-on session with a wake word** — the socket already survives on 8 s `KeepAlive`; a wake word would remove the two taps entirely | 2, and **negative** on cost: billing is per connected minute ($0.075), so an always-on socket is $4.50/hour | 3 h | deliberately not done |

## Why 1, 2 and 3 were the ones built

They are the three that are *inside the voice path itself* (nothing in `ask.py`, `chat.py`, `chat-ui.js` or
the Worker), they fit in the two-hour budget together, and each fixes something a judge could watch fail:

- **#2** fixes the demo's headline claim. The founder's framing is "he asks out loud and the agent answers
  out loud **and opens the manual on the page**." Measured, the second half was not happening at all.
- **#3** fixes the demo's best moment. "And the front one?" is the utterance that proves multi-turn context
  works — and it was the utterance most likely to return the wrong end of the bike.
- **#1** is the one a Deepgram judge will specifically look for, it is the documented feature for exactly
  this vocabulary problem, and it is free. It ships with the measurement that says we could not prove it.

`api/.venv/Scripts/python -m pytest api/tests -q` — **497 passed, 20 skipped**. `node --check` clean on
every JS file touched.
