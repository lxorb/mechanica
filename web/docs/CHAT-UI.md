# Chat UI (2026-09-20) — the forked component

| candidate | stars | licence | verdict |
| --- | --- | --- | --- |
| [deep-chat](https://github.com/OvidijusParsiunas/deep-chat) `2.5.1` | 3 716 | MIT | **chosen** |
| [assistant-ui](https://github.com/assistant-ui/assistant-ui) | 12 217 | MIT | React + Tailwind + a bundler; this app has no build |
| [huggingface/chat-ui](https://github.com/huggingface/chat-ui) | 10 951 | Apache-2.0 | a whole SvelteKit product with MongoDB |
| [botui](https://github.com/botui/botui) | 2 900 | MIT | Vue peer dep, scripted flows, no token streaming |
| [chatscope/chat-ui-kit-react](https://github.com/chatscope/chat-ui-kit-react) | 1 778 | MIT | React only, last push 2025-05 |

## Why deep-chat

One `<deep-chat>` custom element: no framework, no build — a plain ESM `import()` registers it.
`connect = {stream: true, handler}` hands us the request, so nothing ever talks to OpenAI from the browser and
`signals.onResponse({text})` appends into the live bubble, which is exactly our SSE `token` frame. It ships
`htmlClassUtilities` (click handlers + styles inside an `html` message), `addMessage()`, `messageStyles`,
`textInput`, `submitButtonStyles` and `auxiliaryStyle` — enough to repaint it in ink/paper/orange without
patching its source.

## Forked / overridden

- `web/vendor/deep-chat/deepChat.bundle.js` — the pinned 2.5.1 browser bundle (387 KB), vendored so no CDN
  sits in front of the counter. `LICENSE` (MIT) beside it, unmodified. `sw.js` shell-caches `/counter/*` only,
  so this one file is the drawer's sole uncached runtime fetch — owner: sw agent.
- It renders into an open **shadow root**, so `css/chat-ui.css` styles the drawer around it only; every inner
  rule goes through `auxiliaryStyle` and the style properties in `js/chat-ui.js`. Two of its defaults are
  overruled there: `#text-input-container` at `width: 80%`, and `background` shorthands in button styles
  (they come back out as `background-color: unset` — use `backgroundColor`).
- Overridden: every built-in service (only `connect.handler` is used), bubble/input/button styling, error text,
  and the intro message — dropped, so the first bubble is empty.
- Added around it: the drawer chrome, `[p. N]` chips (`htmlClassUtilities.events.click` → `onPage(N)` → a
  one-page synthetic job → `go("book")`), the `tokensSaved` footer, and per-manual in-memory history replayed
  into `history` on reopen.
- Backend: `ttm.chat(manualId, messages, onFrame, {signal})` — `POST /chat`, SSE off a `ReadableStream`,
  `token` frames to `onFrame`, resolves with the `done` frame.
