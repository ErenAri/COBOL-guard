# Workload Identity + KMS Signing Setup

This guide configures CI to sign manifests without private key files by using
GitHub OIDC + cloud KMS.

## Shared Model

1. GitHub Actions obtains short-lived cloud credentials via OIDC.
2. Workflow executes a KMS sign command that receives `{payload_b64}`.
3. Command prints a base64 signature to stdout.
4. `kms-sign-manifest` stores signature envelope JSON.

Release-gate workflow expects these secrets in `kms-command` mode:
- `RELEASE_SIGNER_A_KMS_SIGN_COMMAND`
- `RELEASE_SIGNER_B_KMS_SIGN_COMMAND`

## AWS (Recommended Current Path)

### Prerequisites

- S3 bucket with Object Lock enabled for immutable evidence.
- KMS asymmetric keys for:
  - `release_signer_a`
  - `release_signer_b`
- IAM role trusted by GitHub OIDC provider.

### Required GitHub Secrets

- `AWS_ROLE_TO_ASSUME`
- `AWS_REGION`
- `IMMUTABLE_EVIDENCE_BUCKET`
- optional: `IMMUTABLE_EVIDENCE_PREFIX`
- `RELEASE_SIGNER_A_KMS_SIGN_COMMAND`
- `RELEASE_SIGNER_B_KMS_SIGN_COMMAND`

### Command Template Format

Use script-based templates (avoids shell quoting issues):

```bash
bash tools/workload_identity/aws_kms_sign_command.sh <kms-key-id-or-arn> "{payload_b64}"
```

Example secret values:

```text
RELEASE_SIGNER_A_KMS_SIGN_COMMAND=bash tools/workload_identity/aws_kms_sign_command.sh arn:aws:kms:us-east-1:111122223333:key/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee "{payload_b64}"
RELEASE_SIGNER_B_KMS_SIGN_COMMAND=bash tools/workload_identity/aws_kms_sign_command.sh arn:aws:kms:us-east-1:111122223333:key/ffffffff-1111-2222-3333-444444444444 "{payload_b64}"
```

### OIDC Role Policy (Minimum)

- `kms:Sign` on signer key ARNs
- `s3:PutObject` on immutable evidence bucket/prefix
- `s3:PutObjectRetention` when object lock retention is required

## GCP (Reference Pattern)

- Workload Identity Federation pool/provider for GitHub OIDC.
- Service account with:
  - `cloudkms.cryptoKeyVersions.useToSign`
  - storage object upload permissions for immutable archive bucket.
- KMS sign command must print raw signature bytes as base64.

## Azure (Reference Pattern)

- Federated credential on app registration for GitHub OIDC.
- Key Vault key with sign permissions.
- Blob container with immutable policy (time-based retention/legal hold).
- Sign command must print signature as base64.

## Validation

Use checklist:
- run `.github/workflows/release-gate.yml` in `kms-command` mode
- ensure `release-evidence/.../immutability_proof.json` exists
- ensure `verify-evidence-pack` reports `"passed": true`
