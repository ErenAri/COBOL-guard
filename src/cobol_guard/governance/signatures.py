from __future__ import annotations

import base64
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


@dataclass(frozen=True, slots=True)
class SignatureEnvelope:
    key_id: str
    algorithm: str
    signature_b64: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "key_id": self.key_id,
            "algorithm": self.algorithm,
            "signature_b64": self.signature_b64,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SignatureEnvelope":
        return cls(
            key_id=str(payload["key_id"]),
            algorithm=str(payload["algorithm"]),
            signature_b64=str(payload["signature_b64"]),
        )


def generate_ed25519_keypair(private_path: Path, public_path: Path) -> None:
    private_path.parent.mkdir(parents=True, exist_ok=True)
    public_path.parent.mkdir(parents=True, exist_ok=True)
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    private_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    public_path.write_bytes(
        public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )


def _load_private_key(path: Path) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise TypeError("Expected an Ed25519 private key")
    return key


def _load_public_key(path: Path) -> Ed25519PublicKey:
    key = serialization.load_pem_public_key(path.read_bytes())
    if not isinstance(key, Ed25519PublicKey):
        raise TypeError("Expected an Ed25519 public key")
    return key


def sign_file(manifest_path: Path, private_key_path: Path, key_id: str) -> SignatureEnvelope:
    payload = manifest_path.read_bytes()
    private_key = _load_private_key(path=private_key_path)
    signature = private_key.sign(payload)
    return SignatureEnvelope(
        key_id=key_id,
        algorithm="ed25519",
        signature_b64=base64.b64encode(signature).decode("ascii"),
    )


def sign_file_via_command(
    manifest_path: Path,
    key_id: str,
    command_template: str,
    algorithm: str = "kms-ed25519",
) -> SignatureEnvelope:
    if not command_template.strip():
        raise ValueError("command_template is required for external signing")

    payload = manifest_path.read_bytes()
    payload_b64 = base64.b64encode(payload).decode("ascii")
    command = command_template.format(
        manifest_path=str(manifest_path),
        key_id=key_id,
        payload_b64=payload_b64,
    )
    completed = subprocess.run(command, shell=True, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(
            "external signing command failed "
            f"(exit={completed.returncode}): stdout={completed.stdout.strip()} stderr={completed.stderr.strip()}"
        )

    stdout_lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if not stdout_lines:
        raise RuntimeError("external signing command produced no signature output")
    signature_b64 = stdout_lines[-1]
    try:
        base64.b64decode(signature_b64.encode("ascii"), validate=True)
    except Exception as exc:
        raise RuntimeError("external signing command output is not valid base64 signature") from exc

    return SignatureEnvelope(
        key_id=key_id,
        algorithm=algorithm,
        signature_b64=signature_b64,
    )


def write_signature(signature: SignatureEnvelope, output_path: Path) -> None:
    output_path.write_text(json.dumps(signature.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_signature(path: Path) -> SignatureEnvelope:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return SignatureEnvelope.from_dict(payload)


def verify_signature(manifest_path: Path, signature: SignatureEnvelope, public_key_path: Path) -> bool:
    payload = manifest_path.read_bytes()
    public_key = _load_public_key(path=public_key_path)
    try:
        public_key.verify(base64.b64decode(signature.signature_b64.encode("ascii")), payload)
        return True
    except Exception:
        return False
