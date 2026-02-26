# Release Checklist

Use this checklist for each promoted baseline release (for example `v0.1`).

## 1) Prerequisites

- [ ] `CI` workflow is green for the exact commit being released.
- [ ] Release signer command secrets are configured in GitHub (default signing mode):
  - [ ] `RELEASE_SIGNER_A_KMS_SIGN_COMMAND`
  - [ ] `RELEASE_SIGNER_B_KMS_SIGN_COMMAND`
- [ ] Immutable evidence storage is configured:
  - [ ] `IMMUTABLE_EVIDENCE_BUCKET`
  - [ ] optional `IMMUTABLE_EVIDENCE_PREFIX`
- [ ] OIDC cloud credentials are configured for selected provider:
  - [ ] GCP (recommended): `GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_SERVICE_ACCOUNT`, optional `GCP_PROJECT_ID`
  - [ ] AWS (optional): `AWS_ROLE_TO_ASSUME`, `AWS_REGION`
- [ ] If using `pem-secret` signing mode, private key secrets are configured:
  - [ ] `RELEASE_SIGNER_A_PRIVATE_KEY_PEM`
  - [ ] `RELEASE_SIGNER_B_PRIVATE_KEY_PEM`
- [ ] Public keys are available for signature verification:
  - [ ] committed `governance/keys/release_signer_a.public.pem` and `governance/keys/release_signer_b.public.pem`
  - [ ] or fallback secrets `RELEASE_SIGNER_A_PUBLIC_KEY_PEM`, `RELEASE_SIGNER_B_PUBLIC_KEY_PEM`

## 2) Run Release Gate

- [ ] Trigger `.github/workflows/release-gate.yml` manually with inputs:
  - [ ] `case_path` (default: `fixtures/cases/basic.yml`)
  - [ ] `oracle_mode` (recommended: `cobol-executable`)
  - [ ] `cloud_provider` (recommended: `gcp`)
  - [ ] `signing_mode` (recommended: `kms-command`)
  - [ ] `change_class`
  - [ ] `ticket`
  - [ ] `risk_statement`
  - [ ] `author`
  - [ ] `evidence_pack_id` (example: `v0.1`)
  - [ ] `kms_key_version` (optional metadata)
  - [ ] `immutable_bucket` or secret fallback is set

## 3) Confirm Promotion

- [ ] Workflow completed successfully.
- [ ] Locked baseline artifacts exist for target case:
  - [ ] `baselines/locked/<case_id>/baseline_manifest.json`
  - [ ] `baselines/locked/<case_id>/run_manifest.json`
  - [ ] `baselines/locked/<case_id>/diff_report.json`
  - [ ] `baselines/locked/<case_id>/invariant_report.json`

## 4) Verify Evidence Pack Signatures

- [ ] Download release artifact `release-evidence-<pack_id>` from workflow run.
- [ ] Optional automation: `python tools/run_release_gate.py --ticket ... --risk-statement ... --author ... --evidence-pack-id <pack_id>`
- [ ] Verify evidence-pack integrity + signatures:

```bash
python -m cobol_guard.harness.cli verify-evidence-pack \
  --pack-dir dist/evidence/<pack_id> \
  --signature dist/evidence/<pack_id>/evidence_manifest.release_signer_a.sig.json \
  --signature dist/evidence/<pack_id>/evidence_manifest.release_signer_b.sig.json \
  --keys-dir governance/keys \
  --min-valid 2 \
  --require-key-id release_signer_a \
  --require-key-id release_signer_b
```

- [ ] Verification report indicates `"passed": true`.
- [ ] Immutable upload proof exists at `release-evidence/immutable/immutability_proof.json`.

## 5) Finalize Release

- [ ] Create git tag (example: `v0.1`).
- [ ] Publish GitHub Release.
- [ ] Attach evidence pack zip and signature verification report to release assets.
