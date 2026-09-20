# Hosting
- Live: **https://mechanica.emilvinu.ch** (`/` → `/counter/`), plus `https://trustthemanual.cloudflare-disjoin783.workers.dev`.
- One Cloudflare Worker, `trustthemanual`, on account `Emil Vinu` / zone `emilvinu.ch`. The custom domain
  comes from `routes: [{ pattern, custom_domain: true }]` in `wrangler.jsonc`; Cloudflare owns the proxied
  AAAA record and the certificate — never create that DNS record by hand.
- Static files in `web/` are served directly by the assets runtime. `assets.run_worker_first: ["/api/*"]`
  means only `/api/*` reaches `worker/index.js`, which strips the `/api` prefix and proxies to the FastAPI
  backend on Azure: method, headers and body forwarded (Range included), body streamed back,
  `redirect: "manual"` so `GET /api/manuals/<id>/file` returns its 307 to the blob URL, and
  `Cache-Control: public, max-age=60` added to `GET /api/catalog` and `GET /api/manuals*`.
- The app is therefore same-origin: `<meta name="ttm-api" content="/api">` in `web/counter/index.html`;
  `ttm.js` still falls back to the public Azure URL if `/api/health` fails.
- Redeploy: `bash deploy/web.sh` (token from `C:\Users\me\agent-secrets\cloudflare.txt`).
- **API URL changed?** Edit `API_ORIGIN` at the top of `worker/index.js` *and* `PUBLIC_API` in
  `web/counter/js/ttm.js`, then redeploy. The `<meta>` stays `/api`.
- **Deepgram WebSocket proxy.** `assets.run_worker_first` also covers `/ws/*`, so `worker/index.js`
  answers two upgrades and pipes frames verbatim to Deepgram with an `Authorization: Token` header
  the browser cannot send: `GET /ws/deepgram/agent` → `wss://agent.deepgram.com/v1/agent/converse`,
  `GET /ws/deepgram/listen?<query>` → `wss://api.deepgram.com/v2/listen?<same query>`. Origins are
  limited to the page's own host, `mechanica.emilvinu.ch`, the workers.dev host and localhost; no
  frame is ever logged. This exists because the account's Deepgram key lacks `keys:write`, so
  `/api/voice/deepgram-token` cannot mint a browser credential and 502s — the key lives only here.
  - Secret `DEEPGRAM_API_KEY` (never in `wrangler.jsonc`, never in the repo):
    `printf '%s' "$(tr -d '\r\n' < /c/Users/me/agent-secrets/deepgram.txt)" | npx wrangler secret put DEEPGRAM_API_KEY`
    with `CLOUDFLARE_API_TOKEN` exported. `npx wrangler secret list` to check it survived a deploy.
  - Limits: 1 MiB per WebSocket message (frames here are ~2 KB); no duration cap and only CPU time
    is billed, so an open session costs Deepgram's $0.075/min and next to nothing on Cloudflare.
    Plain Worker invocation, not a Durable Object — a redeploy leaves open sockets alone but
    resumes nothing. Details and the `binaryType` trap: `web/docs/VOICE.md`.
