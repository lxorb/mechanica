# Mechanica pitch brief (shared by every pitch agent)

Product: pick your vehicle (search, photo, or VIN) -> the official manual opens on the exact page, lines marked ->
3D model explodes and highlights the part -> full manual -> exact-fit parts with live prices -> grounded chat + voice.
Live: https://mechanica.emilvinu.ch  API: same origin /api. Repo: C:\Users\me\trustthemanual (read DESIGN.md, docs/ARCHITECTURE.md, docs/PITCH.md, web/QA.md, api/eval/*.md, api/docs/*.md, web/docs/*.md for verified numbers).

The story (true, from the founder): a friend in Germany started his own motorcycle workshop a few years ago.
He spends about 20% of his working time searching manuals instead of working on the bike. He does not use AI:
he does not trust it (95% right is not enough when he is liable for the 5%), and when he tried, one question cost
~$4 in API usage because the model had to read a 500-page manual, so he hit limits constantly.
Mechanica makes the manual the answer (never AI prose), finds the page in seconds, and costs a fraction of a cent.

Numbers to reuse (verify in the repo/live before quoting; say "measured" vs "estimated"):
- 20% of ~2,000 h/year = ~400 h/year searching; at a shop rate of EUR 90-120/h that is EUR 36k-48k/year of billable time per mechanic.
- naive: ~$4-6 per question (whole manual in the flagship model); ours: $0.0003-0.005 per ask/chat (cost log), ~1,500x cheaper.
- registry: 52k rows, 13.5k distinct free official manuals, 27k vehicles (cars + motorcycles), 13k fetchable on demand.
- on-demand manual: readable in ~7 s, fully indexed in ~50 s, ~$0.10.
- chat: 100% valid citations, 0 invented numbers, 0 dealer referrals, tokens saved ~31% (Token Company bear-2), p50 first token ~2.5 s.
- voice: first audio ~0.7-2 s through the Deepgram Voice Agent, grounded via manual tools.
- parts: 135 parts per vehicle, live offers with USD prices, ~7 cents cold, free cached.

Rules for every pitch: 5 minutes total; only mention what is relevant to THAT sponsor; concrete numbers with sources;
a flowchart (mermaid) of the architecture slice that matters to that sponsor; the demo moments and exact inputs;
what the judge should feel at each minute; a Q&A section with hard questions and honest answers; no marketing fluff.
Write to docs/pitches/<sponsor>.md. Screens/diagrams to docs/pitches/<sponsor>/.
