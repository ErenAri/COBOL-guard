from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from cobol_guard.constants import REPO_ROOT


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _iter_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted(item for item in path.rglob("*") if item.is_file())
    raise FileNotFoundError(f"Evidence include path does not exist: {path}")


def _relative_for_pack(path: Path, repo_root: Path) -> Path:
    resolved = path.resolve()
    root = repo_root.resolve()
    try:
        return resolved.relative_to(root)
    except ValueError:
        return Path("_external") / resolved.name


def build_evidence_pack(
    pack_id: str,
    include_paths: list[Path],
    output_dir: Path,
    retention_class: str = "standard",
    immutability_proof_ref: str = "",
    provenance_ref: str = "",
    policy_version: str = "",
    environment: str = "",
    workflow_run_id: str = "",
    repo_root: Path = REPO_ROOT,
    force: bool = False,
) -> dict[str, str | int]:
    normalized_pack_id = str(pack_id).strip()
    if not normalized_pack_id:
        raise ValueError("pack_id is required")
    if not include_paths:
        raise ValueError("At least one include path is required")

    resolved_includes: list[Path] = []
    for include in include_paths:
        candidate = include if include.is_absolute() else (repo_root / include)
        resolved_includes.append(candidate.resolve())

    pack_dir = output_dir / normalized_pack_id
    content_dir = pack_dir / "content"
    if pack_dir.exists():
        if not force:
            raise FileExistsError(f"evidence pack already exists: {pack_dir} (pass force=True to overwrite)")
        shutil.rmtree(pack_dir)
    content_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    copied_paths: list[Path] = []
    seen: set[str] = set()
    for include in resolved_includes:
        for source in _iter_files(include):
            rel = _relative_for_pack(path=source, repo_root=repo_root)
            rel_key = rel.as_posix()
            if rel_key in seen:
                continue
            seen.add(rel_key)
            target = content_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied_paths.append(rel)

    if not copied_paths:
        raise ValueError("No files were collected for evidence pack")

    files = []
    for rel in sorted(copied_paths, key=lambda item: item.as_posix()):
        copied = content_dir / rel
        files.append(
            {
                "path": rel.as_posix(),
                "bytes": copied.stat().st_size,
                "sha256": _sha256_file(copied),
            }
        )

    manifest = {
        "pack_id": normalized_pack_id,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "retention_class": str(retention_class),
        "immutability_proof_ref": str(immutability_proof_ref),
        "provenance_ref": str(provenance_ref),
        "policy_version": str(policy_version),
        "environment": str(environment),
        "workflow_run_id": str(workflow_run_id),
        "file_count": len(files),
        "files": files,
    }
    manifest_path = pack_dir / "evidence_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    archive_path = output_dir / f"{normalized_pack_id}.zip"
    if archive_path.exists():
        if not force:
            raise FileExistsError(f"evidence archive already exists: {archive_path} (pass force=True to overwrite)")
        archive_path.unlink()
    with ZipFile(archive_path, mode="w", compression=ZIP_DEFLATED) as archive:
        archive.write(manifest_path, arcname=f"{normalized_pack_id}/evidence_manifest.json")
        for rel in sorted(copied_paths, key=lambda item: item.as_posix()):
            archive.write(content_dir / rel, arcname=f"{normalized_pack_id}/content/{rel.as_posix()}")

    return {
        "pack_dir": str(pack_dir),
        "manifest_path": str(manifest_path),
        "archive_path": str(archive_path),
        "file_count": len(files),
    }
