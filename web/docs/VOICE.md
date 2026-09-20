# Voice mode

VOICE in the chat input row opens a Deepgram Voice Agent session over the manual on screen.

**Flow.** `GET /voice/agent-settings?manualId=&bikeId=` builds the whole `Settings` message server-side: prompt, models, greeting, a ≤1,500-char digest of the manual's chapters, and the four grounded tools as **server-side** functions (`endpoint.url` = `PUBLIC_BASE/voice/tools/<name>?manualId=…`) — Deepgram calls the API itself, so the manual's text never passes through the tab and the agent cannot name the wrong book.

`js/voice-deepgram.js` opens `wss://mechanica.emilvinu.ch/ws/deepgram/agent` — the Worker's proxy, **no credential in the tab** (see *Socket auth* below) — forwards `settings` unread, streams the mic as 24 kHz linear16 from an AudioWorklet, and plays the returned linear16 through an 80 ms jitter buffer. `show_page` is the one client-side function: it jumps the reader, the same path a `[p. N]` citation chip takes.

**Events.** `Welcome`, `SettingsApplied`, `ConversationText` → a bubble in the same deep-chat history as typed turns, `StartOfTurn`/`UserStartedSpeaking` → barge-in (scheduled audio stops on the next render quantum, <3 ms; the felt wait is Deepgram's event crossing the network, and stray chunks of the abandoned answer are dropped for 500 ms), `AgentThinking`/`AgentStartedSpeaking` → status, `FunctionCallRequest` (client_side) → `show_page` + `FunctionCallResponse`, `AgentAudioDone`, `Error`.

**Config.** listen `flux-general-en` v2, eager/standard EOT 0.4/0.7, `eot_timeout_ms` 2000; think `open_ai` `gpt-4.1` (`MODEL_VOICE` overrides; reasoning models like gpt-5.6-* are impossible — Deepgram sends `reasoning_effort`, which OpenAI rejects with tools attached); speak `aura-2-asteria-en`.

**Limits.** `PUBLIC_BASE` must be https or the endpoints are refused (503 here, not a dead socket). English only. No mic, no toggle.

**Measured** (KTM 390 Duke, "how much engine oil does it take?" spoken into the socket): end of speech → first audio 1.5–2.0 s, end to end 3.9–4.6 s; 4/4 runs called `get_spec` and said the printed 1.5 l.

**Cost** $0.075 per connected minute — the hosted-LLM tier bundles STT, LLM and TTS and bills socket time, not turns, and the socket exists only between the two taps on VOICE.

Screenshots: `web/docs-shots/voice-*.png`. Regenerate with `node web/tools/voice-shots.mjs`.

## Socket auth — the Worker holds the key

A browser WebSocket cannot send headers, so the first design minted a short-lived Deepgram key at `POST /voice/deepgram-token` and shipped it to the tab in the `Sec-WebSocket-Protocol` pair `[scheme, key]`. Minting one needs `keys:write` on the project; this account's key has neither that nor `/v1/auth/grant`, so the endpoint honestly 502s — **in production neither socket could ever open**.

So the key never goes to the browser at all. `worker/index.js` proxies both sockets and adds the real `Authorization: Token` header on the way out:

| browser opens | Worker opens |
| --- | --- |
| `wss://<origin>/ws/deepgram/agent` | `wss://agent.deepgram.com/v1/agent/converse` |
| `wss://<origin>/ws/deepgram/listen?<query>` | `wss://api.deepgram.com/v2/listen?<same query>` |

The Worker accepts the browser's upgrade with a `WebSocketPair`, opens the upstream socket with `fetch(…, {headers:{Upgrade:"websocket"}})` **before** answering the handshake — so the `Settings` message the client sends on `open` can never beat the upstream into existence — and pipes frames verbatim in both directions, closing one when the other closes or errors. Nothing about a frame is logged. Origins are restricted to the page's own host plus `mechanica.emilvinu.ch`, the workers.dev host and localhost; a handshake with no `Origin` (our own probe scripts) is allowed, since only browsers are bound by that check anyway.

Both clients pick the route from `location.hostname`: anything but localhost uses the proxy and sends **no subprotocol**; a page served from localhost has no Worker in front of it and falls back to the `/voice/deepgram-token` path, which is what `web/tools/voice-shots.mjs` fulfils locally with the account key.

**`binaryType`.** Workers defaults a `WebSocket` to `binaryType = "blob"`, and a `Blob` handed back to `send()` leaves as the *text* `[object Blob]`. A transparent audio proxy that forgets this turns every PCM frame into `UNPARSABLE_CLIENT_MESSAGE` upstream and drops every audio frame downstream while the JSON still flows perfectly — the failure looks like "the agent has no voice", not like a bug in the proxy. `raw()` sets `"arraybuffer"` on both ends.

**Worker limits.** One WebSocket message is capped at **1 MiB** (frames here are ~2 KB). Duration is not capped and only CPU time is billed, not the minutes the socket is open, so a proxied session costs Deepgram's $0.075/min and essentially nothing on Cloudflare; the client's 8 s `KeepAlive` also keeps the hop warm. The socket lives in a plain Worker invocation, not a Durable Object: a redeploy does not kill open sessions, but nothing resumes one either — the drawer just reconnects on the next tap.

**Secret.** `DEEPGRAM_API_KEY`, a Worker secret (not in `wrangler.jsonc`, not in the repo):

```sh
printf '%s' "$(tr -d '\r\n' < /c/Users/me/agent-secrets/deepgram.txt)" | npx wrangler secret put DEEPGRAM_API_KEY
```

**Verified** on the live app, headless Chrome, no mic: the agent socket is `wss://mechanica.emilvinu.ch/ws/deepgram/agent` with no subprotocol, `Welcome → SettingsApplied → ConversationText → AgentAudioDone`, **210 binary frames / 201,600 bytes** of greeting audio, first audio 724 ms after the socket opened, status "Listening", **zero console errors**; the dictation socket is `/ws/deepgram/listen?…` and returns `Connected` + `TurnInfo`.
