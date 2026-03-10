import json
from pathlib import Path
from types import SimpleNamespace

from cobol_guard.governance.signatures import generate_ed25519_keypair, sign_file, write_signature
from cobol_guard.harness.cli import cmd_bless, cmd_promote_baseline, cmd_verify
from cobol_guard.harness.run_engine import execute_case


def test_verify_requires_benchmark_report_when_requested(tmp_path: Path) -> None:
    case_path = Path("fixtures/cases/basic.yml")
    oracle_dir = execute_case(target="oracle", case_path=case_path, version="v1", out_root=tmp_path / "runs")
    v2_dir = execute_case(target="v2", case_path=case_path, version="v2", out_root=tmp_path / "runs")
    output_path = tmp_path / "verify_report.json"

    args = SimpleNamespace(
        baseline_dir=str(oracle_dir),
        candidate_dir=str(v2_dir),
        policy=None,
        change_class="bug_fix",
        determinism_case=None,
        determinism_target="v2",
        determinism_repeats=5,
        adapter_parity_case=None,
        benchmark_report=None,
        require_benchmark=True,
        output=str(output_path),
    )

    exit_code = cmd_verify(args)
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert exit_code == 2
    assert payload["performance"]["required"] is True
    assert "performance_gate_failed:benchmark_report_required" in payload["gate_decision"]["blockers"]


def test_promote_baseline_requires_force_to_overwrite(tmp_path: Path) -> None:
    baselines_root = tmp_path / "baselines"
    keys_dir = tmp_path / "keys"
    keys_dir.mkdir(parents=True, exist_ok=True)
    generate_ed25519_keypair(
        private_path=keys_dir / "approver_a.private.pem",
        public_path=keys_dir / "approver_a.public.pem",
    )
    generate_ed25519_keypair(
        private_path=keys_dir / "approver_b.private.pem",
        public_path=keys_dir / "approver_b.public.pem",
    )

    bless_args = SimpleNamespace(
        baseline="candidate",
        target="oracle",
        case="fixtures/cases/basic.yml",
        version=None,
        change_class="bug_fix",
        ticket="REL-100",
        risk_statement="production evidence",
        author="release-bot",
        out_root=str(tmp_path / "runs"),
        baselines_root=str(baselines_root),
        policy=None,
        chunk_size=None,
    )
    assert cmd_bless(bless_args) == 0

    manifest_path = baselines_root / "candidate" / "basic" / "baseline_manifest.json"
    sig_a_path = manifest_path.with_name("baseline_manifest.approver_a.sig.json")
    sig_b_path = manifest_path.with_name("baseline_manifest.approver_b.sig.json")
    write_signature(
        signature=sign_file(
            manifest_path=manifest_path,
            private_key_path=keys_dir / "approver_a.private.pem",
            key_id="approver_a",
        ),
        output_path=sig_a_path,
    )
    write_signature(
        signature=sign_file(
            manifest_path=manifest_path,
            private_key_path=keys_dir / "approver_b.private.pem",
            key_id="approver_b",
        ),
        output_path=sig_b_path,
    )

    promote_args = SimpleNamespace(
        manifest=str(manifest_path),
        signature=[str(sig_a_path), str(sig_b_path)],
        policy=None,
        keys_dir=str(keys_dir),
        baselines_root=str(baselines_root),
        force=False,
    )

    assert cmd_promote_baseline(promote_args) == 0
    assert cmd_promote_baseline(promote_args) == 2

    promote_args.force = True
    assert cmd_promote_baseline(promote_args) == 0
