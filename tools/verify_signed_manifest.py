from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from cobol_guard.governance.signature_verify import verify_manifest_signatures  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify Ed25519 signatures for a manifest file.")
    parser.add_argument("--manifest", required=True, help="Path to manifest JSON to verify")
    parser.add_argument("--signature", required=True, action="append", help="Path to signature envelope JSON")
    parser.add_argument("--keys-dir", default="governance/keys", help="Directory containing <key_id>.public.pem files")
    parser.add_argument("--min-valid", type=int, default=2, help="Minimum number of valid signatures required")
    parser.add_argument(
        "--require-key-id",
        action="append",
        default=[],
        help="Require a specific signer key id to be present among valid signatures",
    )
    parser.add_argument("--output", help="Optional output JSON path for verification report")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    manifest_path = Path(args.manifest).resolve()
    signature_paths = [Path(item).resolve() for item in args.signature]
    keys_dir = Path(args.keys_dir).resolve()
    required = {str(item) for item in args.require_key_id}

    report = verify_manifest_signatures(
        manifest_path=manifest_path,
        signature_paths=signature_paths,
        keys_dir=keys_dir,
        required_key_ids=required,
    )
    valid_count = len(report["valid_signers"])
    passed = valid_count >= int(args.min_valid) and not report["missing_required_key_ids"]
    report["min_valid_required"] = int(args.min_valid)
    report["valid_signature_count"] = valid_count
    report["passed"] = bool(passed)

    payload = json.dumps(report, indent=2, sort_keys=True)
    print(payload)
    if args.output:
        output_path = Path(args.output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload + "\n", encoding="utf-8")

    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
