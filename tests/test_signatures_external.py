from pathlib import Path

import pytest

from cobol_guard.governance.signatures import sign_file_via_command


def test_sign_file_via_command_returns_envelope(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text('{"ok": true}\n', encoding="utf-8")
    command_template = (
        "python -c \"import base64,sys; print(base64.b64encode(base64.b64decode(sys.argv[1])[:8]).decode())\" "
        "\"{payload_b64}\""
    )
    signature = sign_file_via_command(
        manifest_path=manifest_path,
        key_id="kms_signer_a",
        command_template=command_template,
        algorithm="kms-ed25519",
    )
    assert signature.key_id == "kms_signer_a"
    assert signature.algorithm == "kms-ed25519"
    assert len(signature.signature_b64) > 0


def test_sign_file_via_command_raises_on_bad_output(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text('{"ok": true}\n', encoding="utf-8")
    command_template = "python -c \"print('not-base64')\""
    with pytest.raises(RuntimeError):
        sign_file_via_command(
            manifest_path=manifest_path,
            key_id="kms_signer_a",
            command_template=command_template,
            algorithm="kms-ed25519",
        )
