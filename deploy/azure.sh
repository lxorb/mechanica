#!/usr/bin/env bash
# Deploy api/ to Azure Container Apps. Idempotent: safe to re-run.
# Remote-builds the image in ACR (no local Docker needed) and prints the API base URL on the last line.
set -euo pipefail

# az streams ACR build logs through colorama; without this the Windows cp1252 console
# encoding kills the whole command mid-build.
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1

RG="${TTM_RG:-ttm}"
LOC="${TTM_LOCATION:-eastus}"
ENV="${TTM_ENV:-ttm-env}"
APP="${TTM_APP:-ttm-api}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SECRETS_DIR="${SECRETS_DIR:-/c/Users/me/agent-secrets}"
TAG="$(date +%Y%m%d%H%M%S)"

say() { printf '\n== %s\n' "$*" >&2; }

say "subscription"
SUB=$(az account show --query id -o tsv)
az account show --query name -o tsv >&2

say "providers"
for p in Microsoft.App Microsoft.OperationalInsights Microsoft.ContainerRegistry; do
  state=$(az provider show -n "$p" --query registrationState -o tsv 2>/dev/null || echo NotRegistered)
  [ "$state" = "Registered" ] || az provider register -n "$p" --wait >&2
done

say "extension containerapp"
az extension add --name containerapp --upgrade --allow-preview true --only-show-errors >&2 || true

say "resource group $RG ($LOC)"
az group create -n "$RG" -l "$LOC" -o none

say "registry"
ACR=$(az acr list -g "$RG" --query "[0].name" -o tsv 2>/dev/null || true)
if [ -z "$ACR" ]; then
  ACR="ttmacr${SUB//-/}"
  ACR="${ACR:0:20}"
  az acr create -n "$ACR" -g "$RG" -l "$LOC" --sku Basic --admin-enabled true -o none
fi
az acr update -n "$ACR" --admin-enabled true -o none
LOGIN=$(az acr show -n "$ACR" --query loginServer -o tsv)
ACR_USER=$(az acr credential show -n "$ACR" --query username -o tsv)
ACR_PASS=$(az acr credential show -n "$ACR" --query "passwords[0].value" -o tsv)
IMAGE="$LOGIN/ttm-api:$TAG"
echo "registry: $LOGIN" >&2

say "remote build $IMAGE (a few minutes; --no-logs, az cannot stream them on a cp1252 console)"
if ! (cd "$ROOT/api" && az acr build --registry "$ACR" \
        --image "ttm-api:$TAG" --image "ttm-api:latest" \
        --file Dockerfile --no-logs --platform linux . >&2); then
  echo "build failed; recent runs:" >&2
  az acr task list-runs -r "$ACR" --top 3 -o table >&2
  exit 1
fi

say "environment $ENV"
if ! az containerapp env show -n "$ENV" -g "$RG" -o none 2>/dev/null; then
  az containerapp env create -n "$ENV" -g "$RG" -l "$LOC" -o none
fi

OPENAI_KEY="${OPENAI_API_KEY:-}"
if [ -z "$OPENAI_KEY" ] && [ -f "$SECRETS_DIR/openai.txt" ]; then
  OPENAI_KEY=$(tr -d '\r\n' < "$SECRETS_DIR/openai.txt")
fi
if [ -n "$OPENAI_KEY" ]; then
  SECRET_ENV="OPENAI_API_KEY=secretref:openai-key"
else
  echo "warning: no OpenAI key found (\$OPENAI_API_KEY or $SECRETS_DIR/openai.txt)" >&2
  SECRET_ENV=""
fi

say "container app $APP"
if az containerapp show -n "$APP" -g "$RG" -o none 2>/dev/null; then
  az containerapp registry set -n "$APP" -g "$RG" \
    --server "$LOGIN" --username "$ACR_USER" --password "$ACR_PASS" -o none
else
  az containerapp create -n "$APP" -g "$RG" --environment "$ENV" \
    --image "$IMAGE" \
    --registry-server "$LOGIN" --registry-username "$ACR_USER" --registry-password "$ACR_PASS" \
    --ingress external --target-port 8080 --transport auto \
    --min-replicas 1 --max-replicas 3 --cpu 1.0 --memory 2.0Gi \
    --env-vars "CORS_ORIGINS=*" -o none
fi

say "secrets"
if [ -n "$OPENAI_KEY" ]; then
  az containerapp secret set -n "$APP" -g "$RG" --secrets "openai-key=$OPENAI_KEY" -o none
fi

FQDN=$(az containerapp show -n "$APP" -g "$RG" --query properties.configuration.ingress.fqdn -o tsv)
API="https://$FQDN"

say "config: image $TAG, PUBLIC_BASE=$API, 1 CPU / 2Gi, min 1 replica"
# shellcheck disable=SC2086
az containerapp update -n "$APP" -g "$RG" \
  --image "$IMAGE" \
  --set-env-vars "PUBLIC_BASE=$API" "CORS_ORIGINS=*" $SECRET_ENV \
  --min-replicas 1 --max-replicas 3 \
  --cpu 1.0 --memory 2.0Gi -o none

az containerapp ingress update -n "$APP" -g "$RG" --type external --target-port 8080 -o none

say "wait for health"
for _ in $(seq 1 50); do
  code=$(curl -s -o /dev/null -w '%{http_code}' "$API/health" || true)
  [ "$code" = "200" ] && break
  sleep 6
done

say "checks"
curl -fsS "$API/health" >&2 && echo >&2
curl -fsS "$API/manuals" >&2 && echo >&2
curl -s -o /dev/null -w 'manual pdf: %{http_code} %{content_type} %{size_download} bytes\n' \
  "$API/manuals/ktm-390-duke-2024-om-en/file" >&2

say "API"
echo "$API"
