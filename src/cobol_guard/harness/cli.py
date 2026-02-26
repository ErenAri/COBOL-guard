from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cobol_guard.constants import BASELINES_DIR, GOVERNANCE_DIR, KEYS_DIR, RUNS_DIR
from cobol_guard.governance.evidence_pack import build_evidence_pack
from cobol_guard.governance.evidence_verify import verify_evidence_pack
from cobol_guard.governance.policy import evaluate_gate, load_policy
from cobol_guard.governance.signatures import (
    generate_ed25519_keypair,
    read_signature,
    sign_file,
    sign_file_via_command,
    verify_signature,
    write_signature,
)
from cobol_guard.harness.benchmarking import (
    evaluate_benchmark_gates,
    load_benchmark_profile,
    run_benchmark,
    write_benchmark_report,
)
from cobol_guard.harness.diff_engine import diff_runs
from cobol_guard.harness.invariants import evaluate_invariants
from cobol_guard.harness.run_engine import execute_case, load_case
from cobol_guard.io_utils import write_json


def _git_head_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _unique_sorted(items: list[str]) -> list[str]:
    return sorted(set(items))


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _workflow_run_id_from_env() -> str:
    override = os.environ.get("COBOL_GUARD_WORKFLOW_RUN_ID", "")
    if override:
        return override
    return os.environ.get("GITHUB_RUN_ID", "")


def cmd_run(args: argparse.Namespace) -> int:
    version = args.version or ("v1" if args.target == "oracle" else "v2")
    run_dir = execute_case(
        target=args.target,
        case_path=Path(args.case).resolve(),
        version=version,
        deterministic=not args.non_deterministic,
        out_root=Path(args.out_root).resolve() if args.out_root else RUNS_DIR,
        run_id=args.run_id,
        resume=args.resume,
        fail_after_chunks=args.fail_after_chunks,
        chunk_size_override=args.chunk_size,
    )
    print(run_dir)
    return 0


def cmd_bless(args: argparse.Namespace) -> int:
    version = args.version or ("v1" if args.target == "oracle" else "v2")
    run_dir = execute_case(
        target=args.target,
        case_path=Path(args.case).resolve(),
        version=version,
        deterministic=True,
        out_root=Path(args.out_root).resolve() if args.out_root else RUNS_DIR,
        chunk_size_override=args.chunk_size,
    )
    case = load_case(case_path=Path(args.case).resolve())
    policy_path = Path(args.policy).resolve() if args.policy else (GOVERNANCE_DIR / "gate_policy.yml")
    policy = load_policy(path=policy_path)
    run_manifest = _load_json(path=run_dir / "run_manifest.json")
    baseline_case_dir = (
        (Path(args.baselines_root).resolve() if args.baselines_root else BASELINES_DIR) / args.baseline / case.case_id
    )
    baseline_case_dir.mkdir(parents=True, exist_ok=True)
    for artifact in ("ledger_journal.dat", "reconcile_totals.dat", "exception_report.dat", "run_manifest.json"):
        shutil.copy2(run_dir / artifact, baseline_case_dir / artifact)

    self_diff = diff_runs(baseline_dir=run_dir, candidate_dir=run_dir)
    write_json(path=baseline_case_dir / "diff_report.json", payload=self_diff.to_dict())
    invariants = evaluate_invariants(run_dir=run_dir)
    write_json(
        path=baseline_case_dir / "invariant_report.json",
        payload={"invariants": [item.to_dict() for item in invariants]},
    )

    baseline_manifest = {
        "case_id": case.case_id,
        "baseline": args.baseline,
        "source_run_dir": str(run_dir),
        "source_run_id": str(run_manifest.get("run_id", "")),
        "source_run_generated_at_utc": str(run_manifest.get("generated_at_utc", "")),
        "commit_sha": _git_head_sha(),
        "schema_versions": {
            "ledger_journal": "1.0.0",
            "reconcile_totals": "1.0.0",
            "exception_report": "1.0.0",
        },
        "harness_version": "0.1.0",
        "policy_version": str(policy.get("version", "unknown")),
        "policy_sha256": _sha256_file(path=policy_path),
        "workflow_run_id": _workflow_run_id_from_env(),
        "environment": os.environ.get("COBOL_GUARD_ENVIRONMENT", "local"),
        "provenance_ref": os.environ.get("COBOL_GUARD_PROVENANCE_REF", ""),
        "signing_mode": os.environ.get("COBOL_GUARD_SIGNING_MODE", "ed25519-pem"),
        "kms_key_version": os.environ.get("COBOL_GUARD_KMS_KEY_VERSION", ""),
        "change_class": args.change_class,
        "ticket": args.ticket,
        "risk_statement": args.risk_statement,
        "author": args.author,
        "approvers": [],
    }
    write_json(path=baseline_case_dir / "baseline_manifest.json", payload=baseline_manifest)
    print(baseline_case_dir)
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    report = diff_runs(
        baseline_dir=Path(args.baseline_dir).resolve(),
        candidate_dir=Path(args.candidate_dir).resolve(),
    )
    output_path = (
        Path(args.output).resolve() if args.output else Path(args.candidate_dir).resolve() / "diff_report.json"
    )
    write_json(path=output_path, payload=report.to_dict())
    print(output_path)
    return 0


def _run_determinism_check(case_path: Path, target: str, repeats: int) -> tuple[bool, list[str]]:
    hashes: list[str] = []
    for _ in range(repeats):
        run_dir = execute_case(
            target=target,
            case_path=case_path,
            version="v1" if target == "oracle" else "v2",
            deterministic=True,
            out_root=RUNS_DIR,
        )
        manifest = _load_json(run_dir / "run_manifest.json")
        ledger_hash = manifest["artifact_hashes"]["ledger_journal.dat"]
        totals_hash = manifest["artifact_hashes"]["reconcile_totals.dat"]
        exceptions_hash = manifest["artifact_hashes"]["exception_report.dat"]
        hashes.append(f"{ledger_hash}:{totals_hash}:{exceptions_hash}")
    return len(set(hashes)) == 1, hashes


def _run_adapter_parity(case_path: Path) -> tuple[bool, dict[str, Any]]:
    oracle_dir = execute_case(target="oracle", case_path=case_path, version="v1", deterministic=True, out_root=RUNS_DIR)
    v2_dir = execute_case(target="v2", case_path=case_path, version="v2", deterministic=True, out_root=RUNS_DIR)
    report = diff_runs(baseline_dir=oracle_dir, candidate_dir=v2_dir)
    return report.changed_records == 0, report.to_dict()


def cmd_verify(args: argparse.Namespace) -> int:
    baseline_dir = Path(args.baseline_dir).resolve()
    candidate_dir = Path(args.candidate_dir).resolve()
    policy = load_policy(path=Path(args.policy).resolve() if args.policy else GOVERNANCE_DIR / "gate_policy.yml")

    diff_report = diff_runs(baseline_dir=baseline_dir, candidate_dir=candidate_dir)
    invariants = evaluate_invariants(run_dir=candidate_dir)
    invariant_failures = [item.invariant_id for item in invariants if not item.passed]

    determinism_ok = True
    determinism_hashes: list[str] = []
    if args.determinism_case:
        determinism_ok, determinism_hashes = _run_determinism_check(
            case_path=Path(args.determinism_case).resolve(),
            target=args.determinism_target,
            repeats=args.determinism_repeats,
        )
        if not determinism_ok:
            invariant_failures.append("determinism_hash_mismatch")

    adapter_parity_ok = True
    adapter_parity_report: dict[str, Any] = {}
    if args.adapter_parity_case:
        adapter_parity_ok, adapter_parity_report = _run_adapter_parity(case_path=Path(args.adapter_parity_case).resolve())
        if not adapter_parity_ok:
            invariant_failures.append("adapter_parity_mismatch")

    decision = evaluate_gate(
        changed_records_ratio=diff_report.changed_records_ratio,
        changed_fields=diff_report.changed_fields,
        changed_conditions=diff_report.changed_conditions,
        invariant_failures=invariant_failures,
        policy=policy,
        change_class=args.change_class,
    )

    benchmark_payload: dict[str, Any] | None = None
    performance_violations: list[str] = []
    if args.benchmark_report:
        benchmark_payload = _load_json(path=Path(args.benchmark_report).resolve())
        performance_violations = evaluate_benchmark_gates(benchmark_report=benchmark_payload, policy=policy)
        decision.blockers.extend([f"performance_gate_failed:{item}" for item in performance_violations])
        decision.blockers = _unique_sorted(decision.blockers)
        decision.passed = not decision.blockers and not decision.criticals and not decision.majors

    report_payload = {
        "passed": decision.passed,
        "change_class": args.change_class,
        "diff_report": diff_report.to_dict(),
        "invariants": [item.to_dict() for item in invariants],
        "invariant_failures": _unique_sorted(invariant_failures),
        "determinism_check": {
            "enabled": bool(args.determinism_case),
            "target": args.determinism_target,
            "repeats": args.determinism_repeats,
            "passed": determinism_ok,
            "hashes": determinism_hashes,
        },
        "adapter_parity": {
            "enabled": bool(args.adapter_parity_case),
            "passed": adapter_parity_ok,
            "report": adapter_parity_report,
        },
        "performance": {
            "benchmark_report_path": args.benchmark_report,
            "benchmark_report": benchmark_payload,
            "violations": performance_violations,
        },
        "gate_decision": {
            "blockers": decision.blockers,
            "criticals": decision.criticals,
            "majors": decision.majors,
            "minors": decision.minors,
        },
    }
    output_path = Path(args.output).resolve() if args.output else candidate_dir / "verify_report.json"
    write_json(path=output_path, payload=report_payload)
    print(output_path)
    if not decision.passed:
        return 2
    return 0


def cmd_benchmark(args: argparse.Namespace) -> int:
    case = load_case(case_path=Path(args.case).resolve())
    profile = load_benchmark_profile(path=Path(args.profile).resolve())
    report = run_benchmark(
        case_payload={"business_date": case.business_date, "seed_id": case.seed_id},
        profile_payload=profile,
    )
    output_path = (
        Path(args.output).resolve()
        if args.output
        else RUNS_DIR / f"benchmark_{case.case_id}_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    write_benchmark_report(path=output_path, payload=report)
    print(output_path)
    if args.assert_gates:
        policy = load_policy(path=Path(args.policy).resolve() if args.policy else GOVERNANCE_DIR / "gate_policy.yml")
        violations = evaluate_benchmark_gates(benchmark_report=report, policy=policy)
        if violations:
            print("\n".join(violations), file=sys.stderr)
            return 2
    return 0


def cmd_keygen(args: argparse.Namespace) -> int:
    keys_root = Path(args.keys_dir).resolve() if args.keys_dir else KEYS_DIR
    private_path = keys_root / f"{args.name}.private.pem"
    public_path = keys_root / f"{args.name}.public.pem"
    generate_ed25519_keypair(private_path=private_path, public_path=public_path)
    print(public_path)
    return 0


def cmd_sign_manifest(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest).resolve()
    key_path = Path(args.key).resolve()
    key_id = args.key_id or key_path.name.replace(".private.pem", "")
    signature = sign_file(manifest_path=manifest_path, private_key_path=key_path, key_id=key_id)
    output_path = (
        Path(args.output).resolve()
        if args.output
        else manifest_path.with_name(f"{manifest_path.stem}.{key_id}.sig.json")
    )
    write_signature(signature=signature, output_path=output_path)
    print(output_path)
    return 0


def cmd_kms_sign_manifest(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest).resolve()
    command_template = args.command_template or os.environ.get("COBOL_GUARD_KMS_SIGN_COMMAND_TEMPLATE", "")
    if not command_template:
        print(
            "missing command template: pass --command-template or set COBOL_GUARD_KMS_SIGN_COMMAND_TEMPLATE",
            file=sys.stderr,
        )
        return 2
    signature = sign_file_via_command(
        manifest_path=manifest_path,
        key_id=args.key_id,
        command_template=command_template,
        algorithm=args.algorithm,
    )
    output_path = (
        Path(args.output).resolve()
        if args.output
        else manifest_path.with_name(f"{manifest_path.stem}.{args.key_id}.sig.json")
    )
    write_signature(signature=signature, output_path=output_path)
    print(output_path)
    return 0


def _missing_required_evidence(case_dir: Path, policy: dict[str, Any], signature_count: int) -> list[str]:
    required = [str(item) for item in policy.get("required_evidence", [])]
    mapping = {
        "run_manifest": case_dir / "run_manifest.json",
        "diff_report": case_dir / "diff_report.json",
        "invariant_report": case_dir / "invariant_report.json",
        "rationale": case_dir / "baseline_manifest.json",
    }
    missing: list[str] = []
    for item in required:
        if item == "signatures":
            if signature_count <= 0:
                missing.append(item)
            continue
        path = mapping.get(item)
        if path is None:
            continue
        if not path.exists():
            missing.append(item)
    return missing


def cmd_promote_baseline(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest).resolve()
    policy = load_policy(path=Path(args.policy).resolve() if args.policy else GOVERNANCE_DIR / "gate_policy.yml")
    manifest = _load_json(path=manifest_path)

    required_fields = ("change_class", "ticket", "risk_statement")
    missing = [field for field in required_fields if not manifest.get(field)]
    if missing:
        print(f"missing required manifest fields: {', '.join(missing)}", file=sys.stderr)
        return 2

    signatures = [read_signature(path=Path(item).resolve()) for item in args.signature]
    keys_root = Path(args.keys_dir).resolve() if args.keys_dir else KEYS_DIR
    valid_signers: set[str] = set()
    for signature in signatures:
        public_key_path = keys_root / f"{signature.key_id}.public.pem"
        if not public_key_path.exists():
            continue
        if verify_signature(manifest_path=manifest_path, signature=signature, public_key_path=public_key_path):
            valid_signers.add(signature.key_id)

    min_signatures = int(policy["rebless"]["min_signatures"])
    if len(valid_signers) < min_signatures:
        print(f"insufficient valid signatures: {len(valid_signers)} < {min_signatures}", file=sys.stderr)
        return 2

    if manifest["change_class"] not in set(policy["rebless"]["allowed_change_classes"]):
        print(f"disallowed change_class: {manifest['change_class']}", file=sys.stderr)
        return 2

    if bool(policy["rebless"].get("forbid_author_only_approval", False)):
        author = str(manifest.get("author", "")).strip()
        if author and len(valid_signers) == 1 and author in valid_signers:
            print("author_only_approval_not_allowed", file=sys.stderr)
            return 2

    case_id = str(manifest["case_id"])
    baselines_root = Path(args.baselines_root).resolve() if args.baselines_root else BASELINES_DIR
    source_dir = baselines_root / "candidate" / case_id
    missing_evidence = _missing_required_evidence(case_dir=source_dir, policy=policy, signature_count=len(valid_signers))
    if missing_evidence:
        print(f"missing required evidence: {', '.join(_unique_sorted(missing_evidence))}", file=sys.stderr)
        return 2

    target_dir = baselines_root / "locked" / case_id
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    if target_dir.exists():
        shutil.rmtree(target_dir)
    shutil.copytree(source_dir, target_dir)
    print(target_dir)
    return 0


def cmd_evidence_pack(args: argparse.Namespace) -> int:
    policy_path = Path(args.policy).resolve() if args.policy else (GOVERNANCE_DIR / "gate_policy.yml")
    policy = load_policy(path=policy_path)
    output_dir = Path(args.output_dir).resolve() if args.output_dir else (Path.cwd() / "dist" / "evidence")
    result = build_evidence_pack(
        pack_id=args.pack_id,
        include_paths=[Path(item).resolve() if Path(item).is_absolute() else Path(item) for item in args.include],
        output_dir=output_dir,
        retention_class=args.retention_class,
        immutability_proof_ref=args.immutability_proof_ref,
        provenance_ref=args.provenance_ref,
        policy_version=str(policy.get("version", "unknown")),
        environment=os.environ.get("COBOL_GUARD_ENVIRONMENT", "local"),
        workflow_run_id=_workflow_run_id_from_env(),
    )
    if args.output:
        write_json(path=Path(args.output).resolve(), payload=result)
    print(result["archive_path"])
    return 0


def cmd_verify_evidence_pack(args: argparse.Namespace) -> int:
    pack_dir = Path(args.pack_dir).resolve()
    keys_dir = Path(args.keys_dir).resolve() if args.keys_dir else KEYS_DIR
    signature_paths: list[Path] = []
    if args.signature:
        signature_paths = [Path(item).resolve() for item in args.signature]
    else:
        signature_paths = sorted(pack_dir.glob("evidence_manifest.*.sig.json"))
    if not signature_paths:
        print("no evidence signatures found (pass --signature or place evidence_manifest.*.sig.json in pack dir)", file=sys.stderr)
        return 2

    report = verify_evidence_pack(
        pack_dir=pack_dir,
        keys_dir=keys_dir,
        signature_paths=signature_paths,
        min_valid_signatures=args.min_valid,
        required_key_ids={str(item) for item in args.require_key_id},
    )
    payload = json.dumps(report, indent=2, sort_keys=True)
    print(payload)
    if args.output:
        output_path = Path(args.output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload + "\n", encoding="utf-8")
    return 0 if report["passed"] else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gm", description="COBOL Guard harness CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="Run target against a case")
    run_parser.add_argument("--target", required=True, choices=["oracle", "v2"])
    run_parser.add_argument("--case", required=True)
    run_parser.add_argument("--version")
    run_parser.add_argument("--out-root")
    run_parser.add_argument("--run-id")
    run_parser.add_argument("--resume", action="store_true")
    run_parser.add_argument("--fail-after-chunks", type=int)
    run_parser.add_argument("--chunk-size", type=int)
    run_parser.add_argument("--non-deterministic", action="store_true")
    run_parser.set_defaults(func=cmd_run)

    bless_parser = sub.add_parser("bless", help="Run and snapshot a baseline")
    bless_parser.add_argument("--baseline", required=True, choices=["candidate", "locked"])
    bless_parser.add_argument("--target", required=True, choices=["oracle", "v2"])
    bless_parser.add_argument("--case", required=True)
    bless_parser.add_argument("--version")
    bless_parser.add_argument("--change-class", default="bug_fix")
    bless_parser.add_argument("--ticket", default="TBD")
    bless_parser.add_argument("--risk-statement", default="TBD")
    bless_parser.add_argument("--author", default="TBD")
    bless_parser.add_argument("--out-root")
    bless_parser.add_argument("--baselines-root")
    bless_parser.add_argument("--policy")
    bless_parser.add_argument("--chunk-size", type=int)
    bless_parser.set_defaults(func=cmd_bless)

    diff_parser = sub.add_parser("diff", help="Diff two run directories")
    diff_parser.add_argument("--baseline-dir", required=True)
    diff_parser.add_argument("--candidate-dir", required=True)
    diff_parser.add_argument("--output")
    diff_parser.set_defaults(func=cmd_diff)

    verify_parser = sub.add_parser("verify", help="Evaluate release gates")
    verify_parser.add_argument("--baseline-dir", required=True)
    verify_parser.add_argument("--candidate-dir", required=True)
    verify_parser.add_argument("--policy")
    verify_parser.add_argument("--change-class", default="bug_fix")
    verify_parser.add_argument("--determinism-case")
    verify_parser.add_argument("--determinism-target", default="v2", choices=["oracle", "v2"])
    verify_parser.add_argument("--determinism-repeats", default=5, type=int)
    verify_parser.add_argument("--adapter-parity-case")
    verify_parser.add_argument("--benchmark-report")
    verify_parser.add_argument("--output")
    verify_parser.set_defaults(func=cmd_verify)

    benchmark_parser = sub.add_parser("benchmark", help="Generate benchmark report")
    benchmark_parser.add_argument("--case", required=True)
    benchmark_parser.add_argument("--profile", default="benchmark/profile.yml")
    benchmark_parser.add_argument("--output")
    benchmark_parser.add_argument("--policy")
    benchmark_parser.add_argument("--assert-gates", action="store_true")
    benchmark_parser.set_defaults(func=cmd_benchmark)

    keygen_parser = sub.add_parser("keygen", help="Generate Ed25519 keypair")
    keygen_parser.add_argument("--name", required=True)
    keygen_parser.add_argument("--keys-dir")
    keygen_parser.set_defaults(func=cmd_keygen)

    sign_parser = sub.add_parser("sign-manifest", help="Sign a manifest with an Ed25519 private key")
    sign_parser.add_argument("--manifest", required=True)
    sign_parser.add_argument("--key", required=True)
    sign_parser.add_argument("--key-id")
    sign_parser.add_argument("--output")
    sign_parser.set_defaults(func=cmd_sign_manifest)

    kms_sign_parser = sub.add_parser("kms-sign-manifest", help="Sign a manifest using external KMS command")
    kms_sign_parser.add_argument("--manifest", required=True)
    kms_sign_parser.add_argument("--key-id", required=True)
    kms_sign_parser.add_argument("--command-template")
    kms_sign_parser.add_argument("--algorithm", default="kms-ed25519")
    kms_sign_parser.add_argument("--output")
    kms_sign_parser.set_defaults(func=cmd_kms_sign_manifest)

    promote_parser = sub.add_parser("promote-baseline", help="Promote candidate baseline to locked")
    promote_parser.add_argument("--manifest", required=True)
    promote_parser.add_argument("--signature", required=True, action="append")
    promote_parser.add_argument("--policy")
    promote_parser.add_argument("--keys-dir")
    promote_parser.add_argument("--baselines-root")
    promote_parser.set_defaults(func=cmd_promote_baseline)

    evidence_parser = sub.add_parser("evidence-pack", help="Build evidence pack archive")
    evidence_parser.add_argument("--pack-id", required=True)
    evidence_parser.add_argument("--include", required=True, action="append")
    evidence_parser.add_argument("--output-dir", default="dist/evidence")
    evidence_parser.add_argument("--policy")
    evidence_parser.add_argument("--retention-class", default="standard")
    evidence_parser.add_argument("--immutability-proof-ref", default="")
    evidence_parser.add_argument("--provenance-ref", default="")
    evidence_parser.add_argument("--output")
    evidence_parser.set_defaults(func=cmd_evidence_pack)

    evidence_verify_parser = sub.add_parser("verify-evidence-pack", help="Verify evidence pack integrity and signatures")
    evidence_verify_parser.add_argument("--pack-dir", required=True)
    evidence_verify_parser.add_argument("--keys-dir")
    evidence_verify_parser.add_argument("--signature", action="append")
    evidence_verify_parser.add_argument("--min-valid", type=int, default=2)
    evidence_verify_parser.add_argument("--require-key-id", action="append", default=[])
    evidence_verify_parser.add_argument("--output")
    evidence_verify_parser.set_defaults(func=cmd_verify_evidence_pack)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    code = args.func(args)
    raise SystemExit(code)


if __name__ == "__main__":
    main()
