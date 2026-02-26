from __future__ import annotations

from pathlib import Path
from typing import Any

from cobol_guard.governance.signatures import read_signature, verify_signature


def verify_manifest_signatures(
    manifest_path: Path,
    signature_paths: list[Path],
    keys_dir: Path,
    required_key_ids: set[str] | None = None,
) -> dict[str, Any]:
    valid_signers: set[str] = set()
    invalid_signers: set[str] = set()
    missing_public_keys: set[str] = set()

    for signature_path in signature_paths:
        envelope = read_signature(path=signature_path)
        key_id = str(envelope.key_id)
        public_key_path = keys_dir / f"{key_id}.public.pem"
        if not public_key_path.exists():
            missing_public_keys.add(key_id)
            continue
        if verify_signature(manifest_path=manifest_path, signature=envelope, public_key_path=public_key_path):
            valid_signers.add(key_id)
        else:
            invalid_signers.add(key_id)

    required = required_key_ids or set()
    missing_required = sorted(required - valid_signers)
    return {
        "manifest_path": str(manifest_path),
        "keys_dir": str(keys_dir),
        "signature_files": [str(item) for item in signature_paths],
        "valid_signers": sorted(valid_signers),
        "invalid_signers": sorted(invalid_signers),
        "missing_public_keys": sorted(missing_public_keys),
        "required_key_ids": sorted(required),
        "missing_required_key_ids": missing_required,
    }
