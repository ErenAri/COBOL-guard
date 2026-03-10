import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from cobol_guard.governance.evidence_pack import build_evidence_pack


def test_build_evidence_pack_creates_manifest_and_archive(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    include_dir = repo_root / "evidence-input"
    include_dir.mkdir(parents=True, exist_ok=True)
    (repo_root / "SPEC.md").write_text("spec\n", encoding="utf-8")
    (include_dir / "a.txt").write_text("A\n", encoding="utf-8")
    (include_dir / "nested").mkdir(parents=True, exist_ok=True)
    (include_dir / "nested" / "b.txt").write_text("B\n", encoding="utf-8")

    output_dir = tmp_path / "dist" / "evidence"
    result = build_evidence_pack(
        pack_id="v0.1",
        include_paths=[Path("SPEC.md"), Path("evidence-input")],
        output_dir=output_dir,
        retention_class="regulated-7y",
        immutability_proof_ref="s3://bucket/object-lock-ref",
        provenance_ref="gha://run/12345",
        policy_version="1",
        environment="staging",
        workflow_run_id="12345",
        repo_root=repo_root,
    )

    manifest_path = Path(str(result["manifest_path"]))
    archive_path = Path(str(result["archive_path"]))
    assert manifest_path.exists()
    assert archive_path.exists()
    assert int(result["file_count"]) == 3

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["pack_id"] == "v0.1"
    assert manifest["retention_class"] == "regulated-7y"
    assert manifest["immutability_proof_ref"] == "s3://bucket/object-lock-ref"
    assert manifest["provenance_ref"] == "gha://run/12345"
    assert manifest["policy_version"] == "1"
    assert manifest["environment"] == "staging"
    assert manifest["workflow_run_id"] == "12345"
    assert manifest["file_count"] == 3
    paths = [item["path"] for item in manifest["files"]]
    assert "SPEC.md" in paths
    assert "evidence-input/a.txt" in paths
    assert "evidence-input/nested/b.txt" in paths

    with ZipFile(archive_path, "r") as archive:
        names = set(archive.namelist())
    assert "v0.1/evidence_manifest.json" in names
    assert "v0.1/content/SPEC.md" in names
    assert "v0.1/content/evidence-input/a.txt" in names
    assert "v0.1/content/evidence-input/nested/b.txt" in names


def test_build_evidence_pack_requires_force_to_overwrite(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    include_dir = repo_root / "evidence-input"
    include_dir.mkdir(parents=True, exist_ok=True)
    (repo_root / "SPEC.md").write_text("spec\n", encoding="utf-8")
    (include_dir / "a.txt").write_text("A\n", encoding="utf-8")

    output_dir = tmp_path / "dist" / "evidence"
    build_evidence_pack(
        pack_id="v0.1",
        include_paths=[Path("SPEC.md"), Path("evidence-input")],
        output_dir=output_dir,
        repo_root=repo_root,
    )

    with pytest.raises(FileExistsError):
        build_evidence_pack(
            pack_id="v0.1",
            include_paths=[Path("SPEC.md"), Path("evidence-input")],
            output_dir=output_dir,
            repo_root=repo_root,
        )

    result = build_evidence_pack(
        pack_id="v0.1",
        include_paths=[Path("SPEC.md"), Path("evidence-input")],
        output_dir=output_dir,
        repo_root=repo_root,
        force=True,
    )
    assert Path(str(result["manifest_path"])).exists()
