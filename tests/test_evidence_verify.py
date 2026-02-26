from pathlib import Path

from cobol_guard.governance.evidence_pack import build_evidence_pack
from cobol_guard.governance.evidence_verify import verify_evidence_pack
from cobol_guard.governance.signatures import generate_ed25519_keypair, sign_file, write_signature


def _prepare_keys(keys_dir: Path) -> tuple[Path, Path]:
    keys_dir.mkdir(parents=True, exist_ok=True)
    generate_ed25519_keypair(
        private_path=keys_dir / "release_signer_a.private.pem",
        public_path=keys_dir / "release_signer_a.public.pem",
    )
    generate_ed25519_keypair(
        private_path=keys_dir / "release_signer_b.private.pem",
        public_path=keys_dir / "release_signer_b.public.pem",
    )
    return keys_dir / "release_signer_a.private.pem", keys_dir / "release_signer_b.private.pem"


def test_verify_evidence_pack_passes_and_detects_tamper(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    include_dir = repo_root / "evidence-input"
    include_dir.mkdir(parents=True, exist_ok=True)
    (repo_root / "SPEC.md").write_text("spec\n", encoding="utf-8")
    (include_dir / "a.txt").write_text("A\n", encoding="utf-8")

    result = build_evidence_pack(
        pack_id="v0.1",
        include_paths=[Path("SPEC.md"), Path("evidence-input")],
        output_dir=tmp_path / "dist" / "evidence",
        retention_class="regulated-7y",
        immutability_proof_ref="s3://bucket/object-lock-ref",
        provenance_ref="gha://run/12345",
        policy_version="1",
        environment="staging",
        workflow_run_id="12345",
        repo_root=repo_root,
    )
    pack_dir = Path(str(result["pack_dir"]))
    manifest_path = Path(str(result["manifest_path"]))

    signer_a_private, signer_b_private = _prepare_keys(tmp_path / "keys")
    sig_a = pack_dir / "evidence_manifest.release_signer_a.sig.json"
    sig_b = pack_dir / "evidence_manifest.release_signer_b.sig.json"
    write_signature(
        signature=sign_file(manifest_path=manifest_path, private_key_path=signer_a_private, key_id="release_signer_a"),
        output_path=sig_a,
    )
    write_signature(
        signature=sign_file(manifest_path=manifest_path, private_key_path=signer_b_private, key_id="release_signer_b"),
        output_path=sig_b,
    )

    report = verify_evidence_pack(
        pack_dir=pack_dir,
        keys_dir=tmp_path / "keys",
        signature_paths=[sig_a, sig_b],
        min_valid_signatures=2,
        required_key_ids={"release_signer_a", "release_signer_b"},
    )
    assert report["passed"] is True
    assert report["signature_verification"]["passed"] is True
    assert report["integrity_errors"] == []

    # Tamper a content file after signature and hash generation.
    (pack_dir / "content" / "evidence-input" / "a.txt").write_text("tampered\n", encoding="utf-8")
    tampered = verify_evidence_pack(
        pack_dir=pack_dir,
        keys_dir=tmp_path / "keys",
        signature_paths=[sig_a, sig_b],
        min_valid_signatures=2,
        required_key_ids={"release_signer_a", "release_signer_b"},
    )
    assert tampered["passed"] is False
    assert any(item.startswith("sha256_mismatch:") for item in tampered["integrity_errors"])
