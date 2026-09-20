#!/usr/bin/env bash
# Azure Storage for the manual corpus. Idempotent: safe to re-run.
#
#   pdf   container, public blob read  -> the browser fetches PDFs directly (range requests, no API hop)
#   data  container, private           -> manuals/, pages/, specs/, links/, jobs/, costs/, registry.json, bikes.json
#
# stdout is machine readable (KEY=VALUE, one per line) so deploy/azure.sh can consume it:
#   AZURE_STORAGE_ACCOUNT, AZURE_STORAGE_PDF_BASE, AZURE_STORAGE_CONNECTION_STRING
# Everything human goes to stderr.
set -euo pipefail

export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1

RG="${TTM_RG:-ttm}"
LOC="${TTM_LOCATION:-eastus}"
PDF_CONTAINER="${TTM_PDF_CONTAINER:-pdf}"
DATA_CONTAINER="${TTM_DATA_CONTAINER:-data}"

say() { printf '\n== %s\n' "$*" >&2; }

say "subscription"
SUB=$(az account show --query id -o tsv)
az account show --query name -o tsv >&2

say "resource group $RG ($LOC)"
az group create -n "$RG" -l "$LOC" -o none

say "storage account"
SA="${TTM_STORAGE_ACCOUNT:-}"
if [ -z "$SA" ]; then
  SA=$(az storage account list -g "$RG" --query "[?starts_with(name,'ttm')].name | [0]" -o tsv 2>/dev/null || true)
fi
if [ -z "$SA" ] || [ "$SA" = "None" ]; then
  SA="ttm${SUB//-/}"
  SA="${SA:0:24}"
fi
if ! az storage account show -n "$SA" -g "$RG" -o none 2>/dev/null; then
  az storage account create -n "$SA" -g "$RG" -l "$LOC" \
    --sku Standard_LRS --kind StorageV2 \
    --access-tier Hot \
    --allow-blob-public-access true \
    --min-tls-version TLS1_2 -o none
fi
# an account created before this flag existed still needs it for anonymous PDF reads
az storage account update -n "$SA" -g "$RG" --allow-blob-public-access true -o none
echo "account: $SA" >&2

CONN=$(az storage account show-connection-string -n "$SA" -g "$RG" --query connectionString -o tsv)

say "containers ($PDF_CONTAINER public blob, $DATA_CONTAINER private)"
az storage container create -n "$PDF_CONTAINER" --connection-string "$CONN" --public-access blob -o none
az storage container create -n "$DATA_CONTAINER" --connection-string "$CONN" -o none
# a container created before --allow-blob-public-access was on keeps its private ACL
az storage container set-permission -n "$PDF_CONTAINER" --connection-string "$CONN" --public-access blob -o none

say "default service version"
# Anonymous requests otherwise fall back to REST 2009-09-19, which does not send Accept-Ranges: bytes.
# pdf.js reads that header to decide whether it may stream a manual instead of downloading all of it.
az storage account blob-service-properties update \
  -n "$SA" -g "$RG" --default-service-version 2021-08-06 -o none

say "blob CORS (pdf.js issues cross-origin range requests)"
az storage cors clear --services b --connection-string "$CONN" -o none
az storage cors add --services b --connection-string "$CONN" \
  --methods GET HEAD OPTIONS \
  --origins '*' \
  --allowed-headers 'Range' 'Content-Type' 'x-ms-*' \
  --exposed-headers 'Accept-Ranges' 'Content-Range' 'Content-Length' 'Content-Type' 'Content-Encoding' 'ETag' 'Last-Modified' \
  --max-age 3600 -o none

BASE="https://${SA}.blob.core.windows.net/${PDF_CONTAINER}"

say "ready"
{
  echo "account:  $SA"
  echo "pdf base: $BASE"
  echo "data:     https://${SA}.blob.core.windows.net/${DATA_CONTAINER} (private)"
} >&2

echo "AZURE_STORAGE_ACCOUNT=$SA"
echo "AZURE_STORAGE_PDF_BASE=$BASE"
echo "AZURE_STORAGE_PDF_CONTAINER=$PDF_CONTAINER"
echo "AZURE_STORAGE_DATA_CONTAINER=$DATA_CONTAINER"
echo "AZURE_STORAGE_CONNECTION_STRING=$CONN"
