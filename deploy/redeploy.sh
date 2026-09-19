#!/usr/bin/env bash
# Full redeploy: API to Azure Container Apps, then the PWA to Cloudflare against that API.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

API=$(bash "$HERE/azure.sh" | tail -n 1)
echo "API: $API" >&2

WEB=$(bash "$HERE/web.sh" "$API" | tail -n 1)
echo "WEB: $WEB" >&2

printf '%s\n%s\n' "$API" "$WEB"
