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
