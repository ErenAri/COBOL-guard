# Workload Identity + KMS Signing Setup

This guide configures CI to sign manifests without private key files by using
GitHub OIDC + cloud KMS.

## Shared Model

1. GitHub Actions obtains short-lived cloud credentials via OIDC.
2. Workflow executes a KMS sign command that receives `{payload_b64}`.
3. Command prints a base64 signature to stdout.
4. `kms-sign-manifest` stores signature envelope JSON.

Command templates are validated before execution:
- required placeholder: `{payload_b64}`
- positional placeholders are rejected
- unknown placeholders are rejected

Release-gate workflow expects these secrets in `kms-command` mode:
- `RELEASE_SIGNER_A_KMS_SIGN_COMMAND`
- `RELEASE_SIGNER_B_KMS_SIGN_COMMAND`

## GCP (Recommended Current Path)

### Prerequisites

- Workload Identity Federation provider for GitHub OIDC.
- Service account with:
  - `cloudkms.cryptoKeyVersions.useToSign`
  - storage object upload permissions on immutable evidence bucket.
- GCS bucket configured with object retention policy/lock for immutable evidence.
- Two asymmetric KMS keys for:
  - `release_signer_a`
  - `release_signer_b`

### Required GitHub Secrets

- `GCP_WORKLOAD_IDENTITY_PROVIDER`
- `GCP_SERVICE_ACCOUNT`
- optional: `GCP_PROJECT_ID`
- `IMMUTABLE_EVIDENCE_BUCKET`
- optional: `IMMUTABLE_EVIDENCE_PREFIX`
- `RELEASE_SIGNER_A_KMS_SIGN_COMMAND`
- `RELEASE_SIGNER_B_KMS_SIGN_COMMAND`

### Command Template Format

Use script-based templates (avoids shell quoting issues):

```bash
bash tools/workload_identity/gcp_kms_sign_command.sh <project_id> <location> <keyring> <key> <version> "{payload_b64}"
```

Example secret values:

```text
RELEASE_SIGNER_A_KMS_SIGN_COMMAND=bash tools/workload_identity/gcp_kms_sign_command.sh my-project us-central1 release-signers release-signer-a 1 "{payload_b64}"
RELEASE_SIGNER_B_KMS_SIGN_COMMAND=bash tools/workload_identity/gcp_kms_sign_command.sh my-project us-central1 release-signers release-signer-b 1 "{payload_b64}"
```

### Minimum IAM Scope

- KMS sign on signer key versions.
- GCS object create/update metadata on immutable evidence path.

## AWS (Optional Alternate Path)

- IAM role trusted by GitHub OIDC provider.
- S3 bucket with Object Lock enabled.
- KMS asymmetric keys for release signers.

Required secrets:
- `AWS_ROLE_TO_ASSUME`
- `AWS_REGION`
- `IMMUTABLE_EVIDENCE_BUCKET`
- optional: `IMMUTABLE_EVIDENCE_PREFIX`
- `RELEASE_SIGNER_A_KMS_SIGN_COMMAND`
- `RELEASE_SIGNER_B_KMS_SIGN_COMMAND`

Script template:

```bash
bash tools/workload_identity/aws_kms_sign_command.sh <kms-key-id-or-arn> "{payload_b64}"
```

## Azure (Reference Pattern)

- Federated credential on app registration for GitHub OIDC.
- Key Vault key with sign permissions.
- Blob container with immutable policy (time-based retention/legal hold).
- Sign command must print signature as base64.

## Validation

Use checklist:
- run `.github/workflows/release-gate.yml` with `cloud_provider=gcp` and `signing_mode=kms-command`
- confirm the workflow-produced `release-evidence/preflight/benchmark_report.json` is present and that release verification consumed it with benchmark enforcement enabled
- confirm `release-evidence/preflight/release_control_attestation.json` is present and references the captured benchmark/diff/verify artifacts
- confirm `release-evidence/preflight/build_provenance.json` is present and hashes the benchmark/diff/verify/attestation artifacts for the exact workflow run
- confirm `release-evidence/security/security_summary.json` is present beside `pip_audit.json`, `bandit.json`, and `sbom.json`
- review any reported security findings before treating the run as releasable; current workflow publishes these artifacts as auditable evidence even when remediation is deferred
- ensure `release-evidence/immutable/immutability_proof.json` exists
- ensure `verify-evidence-pack` reports `"passed": true`
- note that local reruns of `promote-baseline` and `evidence-pack` now require explicit `--force` when reusing an existing target
