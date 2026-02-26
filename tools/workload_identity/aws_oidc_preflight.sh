#!/usr/bin/env bash
set -euo pipefail

required=(
  AWS_ROLE_TO_ASSUME
  AWS_REGION
  IMMUTABLE_EVIDENCE_BUCKET
  RELEASE_SIGNER_A_KMS_SIGN_COMMAND
  RELEASE_SIGNER_B_KMS_SIGN_COMMAND
)

missing=0
for name in "${required[@]}"; do
  if [ -z "${!name:-}" ]; then
    echo "missing env: $name" >&2
    missing=1
  fi
done

if [ "$missing" -ne 0 ]; then
  exit 2
fi

echo "required env vars are present"
