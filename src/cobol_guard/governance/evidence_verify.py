from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from cobol_guard.governance.signature_verify import verify_manifest_signatures


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def verify_evidence_pack(
    pack_dir: Path,
    keys_dir: Path,
    signature_paths: list[Path],
    min_valid_signatures: int = 2,
    required_key_ids: set[str] | None = None,
) -> dict[str, Any]:
    manifest_path = pack_dir / "evidence_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"evidence manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    content_dir = pack_dir / "content"
    listed_entries = list(manifest.get("files", []))
    integrity_errors: list[str] = []
    for entry in listed_entries:
        rel_path = Path(str(entry["path"]))
        file_path = content_dir / rel_path
        if not file_path.exists():
            integrity_errors.append(f"missing_file:{rel_path.as_posix()}")
            continue
        expected_bytes = int(entry["bytes"])
        expected_sha = str(entry["sha256"])
        actual_bytes = file_path.stat().st_size
        actual_sha = _sha256_file(file_path)
        if actual_bytes != expected_bytes:
            integrity_errors.append(
                f"byte_mismatch:{rel_path.as_posix()} expected={expected_bytes} actual={actual_bytes}"
            )
        if actual_sha != expected_sha:
            integrity_errors.append(
                f"sha256_mismatch:{rel_path.as_posix()} expected={expected_sha} actual={actual_sha}"
            )

    listed_paths = {Path(str(item["path"])).as_posix() for item in listed_entries}
    extra_files: list[str] = []
    if content_dir.exists():
        for item in sorted(path for path in content_dir.rglob("*") if path.is_file()):
            rel = item.relative_to(content_dir).as_posix()
            if rel not in listed_paths:
                extra_files.append(rel)
                integrity_errors.append(f"unexpected_file:{rel}")

    signature_report = verify_manifest_signatures(
        manifest_path=manifest_path,
        signature_paths=signature_paths,
        keys_dir=keys_dir,
        required_key_ids=required_key_ids or set(),
    )
    valid_count = len(signature_report["valid_signers"])
    signature_passed = valid_count >= int(min_valid_signatures) and not signature_report["missing_required_key_ids"]
    passed = not integrity_errors and signature_passed
    return {
        "pack_dir": str(pack_dir),
        "manifest_path": str(manifest_path),
        "integrity_errors": integrity_errors,
        "extra_files": extra_files,
        "file_count_manifest": int(manifest.get("file_count", 0)),
        "file_count_listed": len(listed_entries),
        "signature_verification": {
            **signature_report,
            "min_valid_required": int(min_valid_signatures),
            "valid_signature_count": valid_count,
            "passed": signature_passed,
        },
        "passed": passed,
    }
