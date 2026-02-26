#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "usage: $0 <kms-key-id-or-arn> <payload_b64>" >&2
  exit 2
fi

KEY_ID="$1"
PAYLOAD_B64="$2"
TMP_PAYLOAD="$(mktemp)"
trap 'rm -f "$TMP_PAYLOAD"' EXIT

printf '%s' "$PAYLOAD_B64" | base64 --decode > "$TMP_PAYLOAD"
aws kms sign \
  --key-id "$KEY_ID" \
  --signing-algorithm EDDSA \
  --message-type RAW \
  --message "fileb://$TMP_PAYLOAD" \
  --query Signature \
  --output text
