#!/usr/bin/env bash
# Deploy the Handy Book app (web/, no build step) as the Cloudflare Worker `trustthemanual`.
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
npx wrangler deploy
echo "https://trustthemanual.cloudflare-disjoin783.workers.dev/counter/"
