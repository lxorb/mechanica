# Voice mode

VOICE in the chat input row opens a Deepgram Voice Agent session over the manual on screen. While
it is live the chat is not a chat: it is **the orb** — one round thing in the middle of the view,
breathing on the mic, rippling on a lookup, pulsing on the answer.

**Flow.** `GET /voice/agent-settings?manualId=&bikeId=` builds the whole `Settings` message
server-side: prompt, models, greeting, a ≤1,500-char digest of the manual's chapters, this bike's
keyterms (below), and the four grounded tools as **server-side** functions (`endpoint.url` =
`PUBLIC_BASE/voice/tools/<name>?manualId=…`) — Deepgram calls the API itself, so the manual's text
never passes through the tab and the agent cannot name the wrong book. It also returns `pages` (the
printed page count) and `keyterms` (how many were sent).

`js/voice-deepgram.js` opens `wss://mechanica.emilvinu.ch/ws/deepgram/agent` — the Worker's proxy,
**no credential in the tab** (see *Socket auth* below) — forwards `settings` unread, streams the mic
as 24 kHz linear16 from an AudioWorklet, and plays the returned linear16 through an 80 ms jitter
buffer. `show_page` is the one client-side function: it jumps the reader, the same path a `[p. N]`
citation chip takes.

**Saying a page is showing it.** The prompt makes the agent name the page every figure came off, and
`show_page` exists to open it — but measured against the live socket the model mostly does not call
it: **7 spoken turns, 6 pages named out loud, 0 `show_page` calls**, including on "show me the brake
fluid procedure". So the reader is not left to the model: the page number in the assistant's own
`ConversationText` (`/\bpages?\s+(\d{1,4})\b/`) moves it, bounds-checked against `pages` and never
re-sent for the page already on screen. That transcript arrives on the same millisecond as the first
byte of audio, so the mechanic hears "page 85" and page 85 is already there. `show_page` still wins
when the agent does call it.

> **This is why the prompt asks for the page in DIGITS.** "Page 78, one hundred newton metres" reads
> aloud as "page seventy-eight" — aura-2 says the number, the regex reads the digits. A prompt that
> asked for *"page seventy eight"* in words would sound identical and silently stop the reader
> turning, which is the entire product. `test_voice_conversation.py` guards it.

---

## The conversation, measured before and after

Driven through the live Worker proxy with Deepgram TTS speaking each question into the socket at
real speed, KTM 390 Duke 2024, 2026-09-20. The founder's six-turn script: greeting, a torque, a
follow-up about the other end, an **interruption mid-answer**, "which page was that", "thanks".
Traces saved. Milliseconds are from the last sample of the question.

### Before (the deployed prompt, `I see you're looking at …`)

| turn | first audio | what it said |
|---|---|---|
| greeting | 229 ms | "I see you're looking at the KTM 390 Duke 2024." |
| "what's the torque on the rear axle nut" | 1,957 ms | "Page 78 says the rear axle nut torque is one hundred newton metres." |
| "and the front one?" | 1,681 ms | "Page 130 says the front axle nut torque is forty-five newton metres." |
| **interrupt mid-sentence** — "wait, the brake fluid" | 1,983 ms | "The manual does not print the weight of the brake fluid. **Want the type or quantity instead?**" |
| "which page was that" | 1,886 ms (7,246 ms in the other run) | "No page in this manual gives the brake fluid's weight**;** the brake fluid info starts on **page 84**." |
| "thanks" | 1,079 ms | "You're all set." |

Judged as a shop foreman: it gets the two torques right and it is fast. Everything else is wrong.
It **ends a turn with a question** a man holding a wheel cannot answer. It reads a **semicolon**
out loud. It turns a one-word interruption into `get_spec("brake fluid **weight**")`, answers "the
manual does not print it" off a result that came back about brake *linings*, and **page 85 prints
DOT 4 and DOT 5.1 the whole time**. It names **page 84**, which no result gave it. And the felt
interruption is bad: `UserStartedSpeaking` took **2,242 ms** to cross the network while **102,720
bytes** — two seconds — of the abandoned answer kept arriving.

### After

Five runs of the six turns, medians in bold.

| turn | first audio | what it said |
|---|---|---|
| greeting | **213 ms** (211–251) | "KTM 390 Duke 2024. Go ahead." |
| "what's the torque on the rear axle nut" | **1,775 ms** (1,441–1,850) | "Page 78, one hundred newton metres." |
| "and the front one?" | **1,588 ms** (1,538–1,668) | "Page 130, forty five newton metres." |
| **interrupt mid-sentence** — "wait, the brake fluid" | **ack heard at 2,643 ms** (sent 2,502), answer 5.2 s | "One sec, checking the manual." → "Page 85, brake fluid DOT four or DOT five point one." |
| "which page was that" | **833 ms** (689–962; **no function call at all**) | "Page 85, brake fluid DOT four or DOT five point one." |
| "thanks" | **1,222 ms** (871–1,262) | "You're welcome." |

One sentence a turn, the page first so his eye moves before the number lands, no trailing question,
no punctuation a mouth cannot say, and the brake-fluid answer is **right** — because the prompt now
makes it look twice before it says the manual is silent. `UserStartedSpeaking` came back in
**1,191 ms** and only **8,640 bytes** of the old answer arrived after the interruption started.

### The three turns that got worse before they got better

All three are recorded, because they are the reason the rules are worded the way they are, and
because a prompt rewrite that only reports its wins is a prompt rewrite nobody should trust.

- A draft said *"a result you received earlier in this conversation still counts"* — meant for
  "which page was that?". gpt-4.1 read it as a licence and answered **"and the front one?"** out of
  context with **"Thirty front axle nut"**. The manual prints forty-five. That is the exact failure
  this product exists to prevent, from a *conversational* shortcut. The rule is now **EVERY QUESTION
  IS A NEW QUESTION**, with the repeat-what-you-already-said exception narrowed to the words.
- With the general-steps licence written as "steps and order only", the same draft said **"The usual
  way is DOT four for KTM but this manual does not say"** and then **"Check page 82 or 83."** A fluid
  grade is a specification, and a page is a figure. Both are now named in the licence's exclusions.
- And the one that only showed up once the look-twice rule was in: the brake-fluid turn answered
  correctly at 2.6 s and then **kept going for thirty-five lookups**, twenty-five of them re-reading
  *the same offset of the same page*, and the turn did not finish for **38 seconds**. A model with a
  licence to look again will look again forever. **STOP WHEN YOU HAVE IT** — say it the moment a
  result printed it, and never call a function twice with the same arguments — took the same
  question to **9 lookups and 13 s**. Improvement #4 below is the other half of that fix.

Every rule in `_prompt` is now attached to a turn that broke it, and every one has a test in
`api/tests/test_voice_conversation.py` carrying the reason in its docstring.

---

## One sec, checking the manual

A spec question answers in 1.4–2.1 s. A procedure question walks `find_procedure` and then reads
printed pages, and takes five to ten — in silence. Measured, **no single round trip is slow**: every
one is 250–650 ms. It is the *chain* that is slow, so there is nothing to hang a per-call spinner on.

So the acknowledgement is a **turn-level** timer in `voice-deepgram.js`. If a lookup is running and
the turn has made no sound 2,500 ms after the rider stopped talking, the client sends
`InjectAgentMessage` with `behavior: "queue"` — Deepgram's documented filler-during-a-long-function-
call path. Live: **sent at 2,503 ms, heard at 2,636 ms**, against a real answer at 5,191 ms. Four
seconds of dead air became one sentence and a wait. 2,500 ms sits above the slowest measured spec
turn (2,107 ms), so a two-second answer never earns one, and the prompt knows the app may have
spoken for it so the model neither repeats it nor apologises for the wait.

## Barge-in, before Deepgram says so

`UserStartedSpeaking` is the truth and it is **0.4–2.2 s** away (five sessions; median ~0.7 s, worst
2.2 s). Being talked over for two seconds is the least human thing this agent does. So the mic's own
RMS **ducks** playback locally after ~130 ms of speech while the agent is talking (`DUCK_RMS` 0.05,
three 1,024-sample frames), and the server event turns the duck into a real `flush()`. If no server
event arrives within 900 ms nobody was talking — a dropped spanner, a compressor — and the answer
comes back up where it left off. **A duck is reversible; a flush is not.** Tapping the orb is the
same path, taken deliberately.

## The events Deepgram does not send

Measured over five live sessions on this exact configuration (flux listen v2 + `open_ai` think +
aura-2 speak), the socket sends `Welcome`, `SettingsApplied`, `ConversationText`, `History`,
`LatencyReport`, `UserStartedSpeaking`, `EndOfTurn`, `FunctionCallRequest`, `FunctionCallResponse`
and `AgentAudioDone` — and **never once `AgentThinking` or `AgentStartedSpeaking`**. Those two were
the whole basis of the old "Thinking" and "Speaking" statuses, so **the drawer sat on "Listening"
through every lookup and every answer** and nobody had noticed. The status is now derived from what
actually arrives:

| status | what causes it |
|---|---|
| thinking | `EndOfTurn`, or any `FunctionCallRequest` |
| speaking | the first audio frame of a turn (outside the barge-mute window) |
| listening | the player drained with no lookup in flight, or `SettingsApplied`, or a barge-in |

`AgentThinking` / `AgentStartedSpeaking` are still honoured if they ever turn up.

**One turn is one bubble.** The model emits one `ConversationText` per *sentence*, so a two-sentence
answer used to land as two bubbles from one breath. Sentences after the first of a turn carry
`part: true` and are appended to the message already there.

## The voice: auditioned, not chosen off the adjectives

"Most natural for a workshop" is not a taste question when the room has an impact wrench in it — it
is whether the sentence survives the noise. Each candidate spoke the six lines this agent actually
says (a page and a torque, a tyre pressure, an oil grade, the acknowledgement, a general
procedure); the same synthetic shop noise went in at 3 dB and 0 dB SNR; nova-3 transcribed it back.

| voice | Deepgram's label | pace | WER clean | 3 dB | 0 dB |
|---|---|---|---|---|---|
| **aura-2-asteria-en** | clear, confident, knowledgeable · *advertising* | 2.50 w/s | **8.5%** | **8.5%** | **13.6%** |
| aura-2-orpheus-en | professional, clear, confident, trustworthy · *customer service* | 2.94 w/s | 11.9% | 16.9% | 18.6% |
| aura-2-arcas-en | natural, smooth, clear, comfortable | 2.78 w/s | 11.9% | 22.0% | 23.7% |
| aura-2-harmonia-en | empathetic, clear, calm, confident | 3.17 w/s | 25.4% | 18.6% | 22.0% |

orpheus was the favourite going in, on the labels. It lost on the only thing that matters here: at
3 dB it read **"forty five newton metres"** back as **"forty five millimeters"**, and arcas did the
same at both levels. A torque that arrives as a length is the one mistake this product cannot make.
asteria stays, and it is also the slowest of the four, which is the right direction for a workshop.
`speed` is left at its default: aura-2 would not go below it (0.9 shaved 0.08 s off a 5.12 s line)
and 1.15 only made it quicker, which nobody here wants.

*Honest limit:* this is a round trip through Deepgram's own STT, not a mechanic in a shop. It ranks
intelligibility under noise, which is the thing we can measure; it does not rank warmth.

## One call instead of six (improvement #4)

Live, "wait, the brake fluid" was `get_spec` → `find_procedure` → **four** `read_page` calls, 6.3 s
to the first word. `find_procedure` now returns the best section's **printed text** with it —
`sections[0].text` + `textPages`, sliced out of the same page text `read_page` serves, marked
`[page N]` so the agent can still say which page a step is printed on, capped at
`SECTION_PAGES` 3 / `SECTION_CHARS` 3,600 so the result does not grow into the context budget.
Only the best section carries text; the rest stay places to go.

Measured locally (KTM 390 Duke): the pages travel back in **21–103 ms** of extra work inside
`find_procedure`, and they replace **2–4 model round trips**, each of which cost **~550–800 ms of
model deliberation** in the live trace (`FunctionCallResponse` → next `FunctionCallRequest`) on top
of its API time. **This is an API-side change and is not deployed yet, so the end-to-end number is
arithmetic on measured hops, not a measured end-to-end turn.** Say it that way.

## The orb

![listening](../../docs/voice/orb/listening-phone.png)

`js/voice-orb.js` + `css/voice-orb.css`, mounted by `chat-ui.js` into the conversation — not over
the header, so Back and the chat's own ✕ stay reachable while voice runs.

| state | the disc | under it |
|---|---|---|
| listening | breathes (one 3.4 s cycle, ±3.5%) and rides the **mic's RMS** on top of the breath | LISTENING |
| thinking | dead still; three rings leave the edge on a 1.9 s stagger | THINKING |
| speaking | pulses on the **agent's own output level**, taken from an `AnalyserNode` on the playback gain node | SPEAKING |

The output meter is on the gain node rather than on the incoming chunks because a chunk is scheduled
up to 80 ms before it is audible, and an orb 80 ms ahead of the sound looks broken. One line of live
transcript fades in above it. **Tap** the orb to stop the answer; **long-press** (600 ms) or the ✕ to
leave voice mode; the **chevron** fades the veil and hands the conversation back with the session
still running.

**Sixty frames, no layout.** One `requestAnimationFrame` loop writes two custom properties, `--s`
(scale) and `--g` (glow), and the stylesheet turns those into a `transform` and an `opacity`. No
width, height, margin or offset is ever touched. `web/tools/orb-shots.mjs` asserts that — it records
every inline property the loop set across a second of frames and fails if any of them is not a
custom property — and measures **57–59 frames per second** in both states that move, against **one
scale value** for thinking, which is supposed to be still.

**No layout shift.** The conversation's box is measured before, during and after voice mode; any
difference fails. It is identical at 390×844 and on desktop.

**Reduced motion.** No breath, no ripple, no pulse. The level becomes a ring that fills (`--lvl`
into a conic gradient), which moves nothing, and the state word still changes — that is the part
that carries the meaning. Asserted too: nothing scales, and the ring still takes 30+ distinct values
in 600 ms.

**Themes.** Every colour is a token from `css/counter.css`, so the orb follows the theme switch with
the rest of the app. `css/voice-orb.css` is injected by `voice-orb.js` itself — it is the only
module that needs it and the only one that knows where it lives — so neither `index.html` nor
another agent's screen CSS carries a line for it.

Screenshots: `docs/voice/orb/<state>-{phone,desktop}.png`, plus `peek-` and `reduced-motion-`.
Regenerate and re-verify with `node web/tools/orb-shots.mjs`.

---

**Config.** listen `flux-general-en` v2, eager/standard EOT 0.4/0.7, `eot_timeout_ms` 2000; think
`open_ai` `gpt-4.1` (`MODEL_VOICE` overrides; reasoning models like gpt-5.6-* are impossible —
Deepgram sends `reasoning_effort`, which OpenAI rejects with tools attached); speak
`aura-2-asteria-en`; greeting `"<bike>. Go ahead."`.

**Keyterms.** `agent.listen.provider.keyterms` is [keyterm prompting](https://developers.deepgram.com/docs/keyterm)
in the Voice Agent's own spelling — an array of plain phrases, up to 100 / 500 tokens, supported by
flux and nova-3. `voice.py::_keyterms` builds it per manual, best first, because the cap truncates:
the bike's own name, then the parts this manual names, the specs it prints, its headings and the
rider phrasings each section was indexed under (to 900 chars) — then the `parts-taxonomy.json`
entries for this kind of vehicle, spread one group at a time so the suspension and the wheels are
reached, and skipping anything whose words are already primed. KTM 390 Duke: **100 terms, 1,413
chars**. Headings are reduced to the noun phrase ("Checking the engine oil level" → "engine oil
level"), index order is un-inverted ("Nut, rear wheel spindle" → "rear wheel spindle Nut"), and
anything longer than five words is dropped rather than cut.

*Honest measurement:* accepted by the live socket at the full 100 terms, zero errors. A/B'd on
`wss://…/ws/deepgram/listen` against Deepgram TTS speech mixed with synthetic shop noise — **3 dB
SNR: 11.4% WER without, 13.6% with (n=88 words); 0 dB SNR: 14.1% without, 13.3% with (n=135)**. That
is noise, not a win. Individual terms flipped both ways ("rear brake kit" → "rear brake disc" with;
"oil screen" → "oil stream" with). It ships because it is the documented lever, costs nothing and
protects the proper nouns — but a real claim needs real mechanics in a real shop, not a TTS voice.

**Limits.** `PUBLIC_BASE` must be https or the endpoints are refused (503 here, not a dead socket).
English only. No mic, no toggle.

**Probing it from node.** Since 2026-09-20 the Worker refuses a WebSocket handshake that carries no
`Origin` (BUG-10: everything that is not a browser also sends none, so the old "no Origin means one
of our own scripts" exemption was an open door to `DEEPGRAM_API_KEY`). That is the right call and it
locks out every node probe, because the WHATWG `WebSocket` in node cannot set a header. Use the `ws`
package, which can: `new WebSocket(url, { origin: "https://mechanica.emilvinu.ch" })`. Headless-Chrome
harnesses (`web/tools/voice-shots.mjs`, `web/tools/orb-shots.mjs`) are unaffected.

**Where the milliseconds go** (live, through the Worker proxy; KTM 390 Duke; the settings above):

| hop | measured |
|---|---|
| socket open → `Welcome` | 2–10 ms |
| → `SettingsApplied` | 127–166 ms |
| → greeting audio | **184–251 ms** |
| `get_spec` round trip | 250–650 ms |
| `read_page` round trip | 110–330 ms |
| one extra tool hop, model time only | ~550–800 ms |
| spec turn, end of question → first audio | **1,441–1,850 ms** |
| `UserStartedSpeaking` after the rider starts talking | 384–2,242 ms |
| local duck (mic RMS) | **~130 ms**, no network |
| barge-in local stop | **<3 ms** (next render quantum) + a 500 ms window that drops the abandoned answer's chunks |
| cost | **$0.075 per connected minute** — the hosted tier bundles STT + LLM + TTS and bills socket time, and the socket exists only between the two taps on VOICE |

Screenshots: `web/docs-shots/voice-*.png`. Regenerate with `node web/tools/voice-shots.mjs`.

## Socket auth — the Worker holds the key

A browser WebSocket cannot send headers, so the first design minted a short-lived Deepgram key at
`POST /voice/deepgram-token` and shipped it to the tab in the `Sec-WebSocket-Protocol` pair
`[scheme, key]`. Minting one needs `keys:write` on the project; this account's key has neither that
nor `/v1/auth/grant`, so the endpoint honestly 502s — **in production neither socket could ever
open**.

So the key never goes to the browser at all. `worker/index.js` proxies both sockets and adds the
real `Authorization: Token` header on the way out:

| browser opens | Worker opens |
| --- | --- |
| `wss://<origin>/ws/deepgram/agent` | `wss://agent.deepgram.com/v1/agent/converse` |
| `wss://<origin>/ws/deepgram/listen?<query>` | `wss://api.deepgram.com/v2/listen?<same query>` |

The Worker accepts the browser's upgrade with a `WebSocketPair`, opens the upstream socket with
`fetch(…, {headers:{Upgrade:"websocket"}})` **before** answering the handshake — so the `Settings`
message the client sends on `open` can never beat the upstream into existence — and pipes frames
verbatim in both directions, closing one when the other closes or errors. Nothing about a frame is
logged. Origins are restricted to the page's own host plus `mechanica.emilvinu.ch`, the workers.dev
host and localhost; a handshake with no `Origin` (our own probe scripts) is allowed, since only
browsers are bound by that check anyway.

Both clients pick the route from `location.hostname`: anything but localhost uses the proxy and
sends **no subprotocol**; a page served from localhost has no Worker in front of it and falls back
to the `/voice/deepgram-token` path, which is what `web/tools/voice-shots.mjs` fulfils locally with
the account key.

**`binaryType`.** Workers defaults a `WebSocket` to `binaryType = "blob"`, and a `Blob` handed back
to `send()` leaves as the *text* `[object Blob]`. A transparent audio proxy that forgets this turns
every PCM frame into `UNPARSABLE_CLIENT_MESSAGE` upstream and drops every audio frame downstream
while the JSON still flows perfectly — the failure looks like "the agent has no voice", not like a
bug in the proxy. `raw()` sets `"arraybuffer"` on both ends.

**Worker limits.** One WebSocket message is capped at **1 MiB** (frames here are ~2 KB). Duration is
not capped and only CPU time is billed, not the minutes the socket is open, so a proxied session
costs Deepgram's $0.075/min and essentially nothing on Cloudflare; the client's 8 s `KeepAlive` also
keeps the hop warm. The socket lives in a plain Worker invocation, not a Durable Object: a redeploy
does not kill open sessions, but nothing resumes one either — the view just reconnects on the next
tap.

**Secret.** `DEEPGRAM_API_KEY`, a Worker secret (not in `wrangler.jsonc`, not in the repo):

```sh
printf '%s' "$(tr -d '\r\n' < /c/Users/me/agent-secrets/deepgram.txt)" | npx wrangler secret put DEEPGRAM_API_KEY
```

**Verified** on the live app, headless Chrome, no mic: the agent socket is
`wss://mechanica.emilvinu.ch/ws/deepgram/agent` with no subprotocol, `Welcome → SettingsApplied →
ConversationText → AgentAudioDone`, **210 binary frames / 201,600 bytes** of greeting audio, first
audio 724 ms after the socket opened, **zero console errors**; the dictation socket is
`/ws/deepgram/listen?…` and returns `Connected` + `TurnInfo`.
