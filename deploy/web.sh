#!/usr/bin/env bash
# Build the PWA against the live API and deploy the Cloudflare Worker `trustthemanual`.
#   deploy/web.sh https://<api-fqdn>      (or VITE_API_URL=... deploy/web.sh)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SECRETS_DIR="${SECRETS_DIR:-/c/Users/me/agent-secrets}"

API="${1:-${VITE_API_URL:-}}"
if [ -z "$API" ]; then
  echo "usage: deploy/web.sh https://<api-fqdn>" >&2
  exit 2
fi
API="${API%/}"

if [ -z "${CLOUDFLARE_API_TOKEN:-}" ]; then
  [ -f "$SECRETS_DIR/cloudflare.txt" ] || { echo "no Cloudflare token" >&2; exit 2; }
  CLOUDFLARE_API_TOKEN=$(tr -d '\r\n' < "$SECRETS_DIR/cloudflare.txt")
fi
export CLOUDFLARE_API_TOKEN

cd "$ROOT"
echo "== build (VITE_API_URL=$API)" >&2
VITE_API_URL="$API" npm run build

echo "== deploy worker" >&2
npx wrangler deploy

WEB="https://trustthemanual.cloudflare-disjoin783.workers.dev"
echo "== live" >&2
printf 'web: %s\n' "$(curl -s -o /dev/null -w '%{http_code}' "$WEB/")" >&2
printf 'api: %s\n' "$(curl -s -o /dev/null -w '%{http_code}' "$API/health")" >&2

echo "$WEB"
