#!/usr/bin/env bash
# Deploy the Mechanica app (web/, no build step) as the Cloudflare Worker `trustthemanual`.
#   deploy/web.sh            (API base is the <meta name="ttm-api"> in web/counter/index.html)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SECRETS_DIR="${SECRETS_DIR:-/c/Users/me/agent-secrets}"
if [ -z "${CLOUDFLARE_API_TOKEN:-}" ]; then
  [ -f "$SECRETS_DIR/cloudflare.txt" ] || { echo "no Cloudflare token" >&2; exit 2; }
  CLOUDFLARE_API_TOKEN=$(tr -d '\r\n' < "$SECRETS_DIR/cloudflare.txt")
fi
export CLOUDFLARE_API_TOKEN
cd "$ROOT"
# `vite build` leaves a redirect that makes wrangler deploy dist/ (the old React build)
# instead of the wrangler.jsonc next to it, which serves web/. There is no build step here.
rm -f .wrangler/deploy/config.json
npx wrangler deploy --config wrangler.jsonc
echo "https://mechanica.emilvinu.ch/counter/  (also https://trustthemanual.cloudflare-disjoin783.workers.dev/counter/)"
