# Voice mode

VOICE in the chat input row opens a Deepgram Voice Agent session over the manual on screen.

**Flow.** `GET /voice/agent-settings?manualId=&bikeId=` builds the whole `Settings` message on the
server — prompt, models, greeting, a ≤1,500-char digest of the manual's chapters, and the four
grounded tools as **server-side** functions (`endpoint.url` = `PUBLIC_BASE/voice/tools/<name>?manualId=…`,
so Deepgram calls the API itself and the manual's text never passes through the tab). The browser
(`js/voice-deepgram.js`) mints a key at `POST /voice/deepgram-token`, opens
`wss://agent.deepgram.com/v1/agent/converse` with the `[scheme, key]` subprotocol (a browser socket
has no headers), forwards `settings` unread, streams the mic as 24 kHz linear16 from an AudioWorklet,
and plays the returned linear16 through an 80 ms jitter buffer. `show_page` is the one client-side
function: it jumps the reader, same path as a `[p. N]` citation chip.

**Events handled.** `Welcome`, `SettingsApplied`, `ConversationText` → a bubble in the same deep-chat
history as typed turns, `StartOfTurn`/`UserStartedSpeaking` → barge-in (playback stops on the next
render quantum, <3 ms local; the wait is Deepgram's event crossing the network, and late chunks of the
abandoned answer are dropped for 500 ms), `AgentThinking`/`AgentStartedSpeaking` → status,
`FunctionCallRequest` (client_side) → `show_page` + `FunctionCallResponse`, `AgentAudioDone`, `Error`.

**Config.** listen `flux-general-en` v2, `eager_eot_threshold` 0.4 / `eot_threshold` 0.7 /
`eot_timeout_ms` 2000; think `open_ai` `gpt-4.1` (`MODEL_VOICE` overrides — reasoning models such as
gpt-5.6-* cannot be used: Deepgram sends `reasoning_effort`, which OpenAI rejects with tools attached);
speak `aura-2-asteria-en`.

**Limits.** `PUBLIC_BASE` must be `https://` or the endpoints are refused (503 here, not a dead socket).
The Deepgram account key needs `keys:write` to mint a browser credential; without it
`/voice/deepgram-token` 502s and VOICE reports "Voice unavailable". English only. No mic, no toggle.

**Measured** (KTM 390 Duke, "how much engine oil does it take?" spoken into the socket): end of speech
→ first audio 1.5–2.0 s; end to end 3.9–4.6 s; 4/4 runs called `get_spec` and said the printed 1.5 l.

**Cost.** $0.075 per connected minute, pay-as-you-go: the Voice Agent hosted-LLM tier bills websocket
time and bundles STT, the LLM and TTS (BYO LLM+TTS would be $0.050). Billed on connection time, not on
turns, so the socket only exists between the two taps on VOICE — a five-turn session is about 4 cents.
