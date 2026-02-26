from pathlib import Path

from cobol_guard.governance.signature_verify import verify_manifest_signatures
from cobol_guard.governance.signatures import generate_ed25519_keypair, sign_file, write_signature


def test_verify_manifest_signatures_detects_valid_and_missing_keys(tmp_path: Path) -> None:
    keys_dir = tmp_path / "keys"
    keys_dir.mkdir(parents=True, exist_ok=True)
    generate_ed25519_keypair(
        private_path=keys_dir / "signer_a.private.pem",
        public_path=keys_dir / "signer_a.public.pem",
    )
    generate_ed25519_keypair(
        private_path=keys_dir / "signer_b.private.pem",
        public_path=keys_dir / "signer_b.public.pem",
    )

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text('{"ok": true}\n', encoding="utf-8")

    sig_a_path = tmp_path / "manifest.signer_a.sig.json"
    sig_b_path = tmp_path / "manifest.signer_b.sig.json"
    sig_c_path = tmp_path / "manifest.signer_c.sig.json"
    write_signature(
        signature=sign_file(manifest_path=manifest_path, private_key_path=keys_dir / "signer_a.private.pem", key_id="signer_a"),
        output_path=sig_a_path,
    )
    write_signature(
        signature=sign_file(manifest_path=manifest_path, private_key_path=keys_dir / "signer_b.private.pem", key_id="signer_b"),
        output_path=sig_b_path,
    )
    write_signature(
        signature=sign_file(manifest_path=manifest_path, private_key_path=keys_dir / "signer_b.private.pem", key_id="signer_c"),
        output_path=sig_c_path,
    )

    report = verify_manifest_signatures(
        manifest_path=manifest_path,
        signature_paths=[sig_a_path, sig_b_path, sig_c_path],
        keys_dir=keys_dir,
        required_key_ids={"signer_a", "signer_b"},
    )
    assert report["valid_signers"] == ["signer_a", "signer_b"]
    assert report["missing_public_keys"] == ["signer_c"]
    assert report["missing_required_key_ids"] == []
