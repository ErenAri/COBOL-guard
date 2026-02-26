# Governance Keys

Approved signer public keys live in this directory.
The standardized release-gate signer ids are `release_signer_a` and `release_signer_b`.

Use:
- `gm keygen --name <id>` to generate a key pair.
- Keep `<id>.private.pem` secure and out of source control.
- Commit only `release_signer_a.public.pem` and `release_signer_b.public.pem` for release-gate CI verification.

Release gate workflow defaults:
- `release_signer_a.public.pem`
- `release_signer_b.public.pem`

If these files are not committed, `release-gate.yml` can load them from secrets:
- `RELEASE_SIGNER_A_PUBLIC_KEY_PEM`
- `RELEASE_SIGNER_B_PUBLIC_KEY_PEM`

Default release signing mode is `kms-command` (no private key files in CI) via:
- `RELEASE_SIGNER_A_KMS_SIGN_COMMAND`
- `RELEASE_SIGNER_B_KMS_SIGN_COMMAND`

Any other `*.public.pem` files are intentionally git-ignored to avoid key sprawl.
