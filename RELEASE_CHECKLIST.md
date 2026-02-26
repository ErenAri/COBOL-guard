# Release Checklist

Use this checklist for each promoted baseline release (for example `v0.1`).

## 1) Prerequisites

- [ ] `CI` workflow is green for the exact commit being released.
- [ ] Release signer private key secrets are configured in GitHub:
  - [ ] `RELEASE_SIGNER_A_PRIVATE_KEY_PEM`
  - [ ] `RELEASE_SIGNER_B_PRIVATE_KEY_PEM`
- [ ] Public keys are available for signature verification:
  - [ ] committed `governance/keys/release_signer_a.public.pem` and `governance/keys/release_signer_b.public.pem`
  - [ ] or fallback secrets `RELEASE_SIGNER_A_PUBLIC_KEY_PEM`, `RELEASE_SIGNER_B_PUBLIC_KEY_PEM`

## 2) Run Release Gate

- [ ] Trigger `.github/workflows/release-gate.yml` manually with inputs:
  - [ ] `case_path` (default: `fixtures/cases/basic.yml`)
  - [ ] `oracle_mode` (recommended: `cobol-executable`)
  - [ ] `change_class`
  - [ ] `ticket`
  - [ ] `risk_statement`
  - [ ] `author`
  - [ ] `evidence_pack_id` (example: `v0.1`)

## 3) Confirm Promotion

- [ ] Workflow completed successfully.
- [ ] Locked baseline artifacts exist for target case:
  - [ ] `baselines/locked/<case_id>/baseline_manifest.json`
  - [ ] `baselines/locked/<case_id>/run_manifest.json`
  - [ ] `baselines/locked/<case_id>/diff_report.json`
  - [ ] `baselines/locked/<case_id>/invariant_report.json`

## 4) Verify Evidence Pack Signatures

- [ ] Download release artifact `release-evidence-<pack_id>` from workflow run.
- [ ] Verify evidence manifest signatures:

```bash
python tools/verify_signed_manifest.py \
  --manifest dist/evidence/<pack_id>/evidence_manifest.json \
  --signature dist/evidence/<pack_id>/evidence_manifest.release_signer_a.sig.json \
  --signature dist/evidence/<pack_id>/evidence_manifest.release_signer_b.sig.json \
  --keys-dir governance/keys \
  --min-valid 2 \
  --require-key-id release_signer_a \
  --require-key-id release_signer_b
```

- [ ] Verification report indicates `"passed": true`.

## 5) Finalize Release

- [ ] Create git tag (example: `v0.1`).
- [ ] Publish GitHub Release.
- [ ] Attach evidence pack zip and signature verification report to release assets.
