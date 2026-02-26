#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 6 ]; then
  echo "usage: $0 <project_id> <location> <keyring> <key> <version> <payload_b64>" >&2
  exit 2
fi

PROJECT_ID="$1"
LOCATION="$2"
KEYRING="$3"
KEY="$4"
VERSION="$5"
PAYLOAD_B64="$6"

TMP_PAYLOAD="$(mktemp)"
TMP_SIGNATURE="$(mktemp)"
trap 'rm -f "$TMP_PAYLOAD" "$TMP_SIGNATURE"' EXIT

printf '%s' "$PAYLOAD_B64" | base64 --decode > "$TMP_PAYLOAD"

gcloud kms asymmetric-sign \
  --project="$PROJECT_ID" \
  --location="$LOCATION" \
  --keyring="$KEYRING" \
  --key="$KEY" \
  --version="$VERSION" \
  --input-file="$TMP_PAYLOAD" \
  --signature-file="$TMP_SIGNATURE" \
  --quiet

# gcloud writes signature in base64 format; emit as single-line stdout.
tr -d '\n' < "$TMP_SIGNATURE"
