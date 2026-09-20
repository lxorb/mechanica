# Chat research (2026-09-20)

## 1. The Token Company — verified live against the real key, not from the docs page

The published docs page only shows the SDK snippet (`pip install the-token-company`, `client.compress(text)`
-> `.output` / `.tokens_saved` / `.compression_ratio`). The HTTP contract below was **probed directly**.

- `POST https://api.thetokencompany.com/v1/compress`, `Authorization: Bearer ttc-...`
  (optional `Content-Encoding: gzip` — send a gzipped body, the API gzips the reply back)
- Body: `{"model": "bear-2", "input": "<text>", "compression_settings": {"aggressiveness": 0.3}}`
- Reply: `{"output": "<text>", "output_tokens": 58, "original_input_tokens": 100, "compression_time": 0.064}`
- Models (a 422 lists them): `bear-1.2`, `bear-2`, `bear-2-meeting-2`, `bear-2.5`. **`bear-2-safety` does not exist.**
- `aggressiveness` is open at both ends: `0.0` and `1.0` -> 422. Omitting `compression_settings` behaves like ~0.5.
- Empty `input` -> 422. 90 000 tokens in one call -> 35 069 out in 0.69 s, so our 6-page budget is nowhere near a limit.
- **Undocumented and the single most important finding: 60 requests/minute.** Over it, `429
  {"detail":"Rate limit exceeded: 60 requests/minute"}`. One call per page would have capped the whole app at
  ten chats a minute, so chat compresses the entire prompt in ONE call with `PAGE N` fences.
- Pricing: "you only pay for the tokens compression removes" — no public $/M, so it is logged as `usd = 0`
  and the saving is counted in tokens instead (`GET /cost/ttc`).

## 2. Why aggressiveness is pinned at 0.3, and why we miss the 30 % target on purpose

Measured on the six real retrieved chat contexts, one batched call each:

| aggressiveness | tokens saved | `PAGE N` fences intact | printed figures kept |
| --- | --- | --- | --- |
| 0.3 | 19.4 % | 6/6 | 86 % |
| 0.5 | **32.2 %** | 4/6 | 80 % |

bear-2 is extractive: it strips stopwords and punctuation, and at 0.5 it also eats printed values and
sometimes a page fence. A lost fence silently reattributes one page's text to another page's number, and a
lost torque figure is exactly the thing this app exists not to get wrong. So we stayed at 0.3 and accepted
~22 %, under the 30 % target — and then got the rest for free from the other end: `chat._strip_referrals`
deletes the "consult an authorised workshop" boilerplate (2.8 % of the KTM text, 5.7 % of the BMW) before
compression, which a mechanic must not be told anyway. Measured end to end that lands at **30.8 % saved with
every printed figure intact** — 368/368 KTM and 256/256 BMW figures survive stripping. Cutting text that
carries no information beats compressing text that does. Two guards keep it safe: `chat._split` re-checks
every fence and throws the whole compression away if one is missing, and no quote is ever copied out of
compressed text (see §3); stripping touches only the model's context, never the page a quote is sliced from.

## 3. Adopted reference: LlamaIndex `CitationQueryEngine`

`run-llama/llama_index` — https://github.com/run-llama/llama_index — **MIT**, ~44k stars.
File: `llama-index-core/llama_index/core/query_engine/citation_query_engine.py` (`CITATION_QA_TEMPLATE`).

Taken: the retrieve -> number every chunk -> "answer based solely on the provided sources, cite the
corresponding numbers, every answer includes at least one citation, only cite what you reference, say so when
no source helps" loop; the worked two-source example that teaches the citation format before the real sources
arrive; the `------`-fenced source block.

Changed: the chunk number **is the printed page number**, so `Source 1`/`[1]` becomes `Page 84`/`[p. 84]` and a
citation is somewhere the rider can be sent; chunking is per manual page, not `SentenceSplitter(512/20)`; added
the no-invented-figures bans and Responses-API streaming. Because compression makes passages unquotable, the
model only ever emits page numbers and the server slices each `quote` out of the ORIGINAL page text, so
citations are verbatim by construction (100 % valid over the eval) rather than by trusting the model.

Rejected: LangChain "chat with your PDF" (loop buried in LCEL runnables), open-webui, Verba, PrivateGPT, Onyx
(whole products; citation logic entangled with their own vector stores).
