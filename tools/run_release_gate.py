from __future__ import annotations

import argparse
import base64
from datetime import UTC, datetime
import json
import subprocess
import time
from pathlib import Path

import yaml


def _run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=check, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dispatch release-gate workflow and download golden evidence artifact.")
    parser.add_argument("--repo", default="ErenAri/COBOL-Guard")
    parser.add_argument("--ref", default="main")
    parser.add_argument("--case-path", default="fixtures/cases/basic.yml")
    parser.add_argument("--oracle-mode", default="cobol-executable", choices=["cobol-executable", "python-reference"])
    parser.add_argument("--signing-mode", default="kms-command", choices=["kms-command", "pem-secret"])
    parser.add_argument("--change-class", default="bug_fix")
    parser.add_argument("--ticket", required=True)
    parser.add_argument("--risk-statement", required=True)
    parser.add_argument("--author", required=True)
    parser.add_argument("--evidence-pack-id", default="v0.1")
    parser.add_argument("--kms-key-version", default="")
    parser.add_argument("--immutable-bucket", default="")
    parser.add_argument("--immutable-prefix", default="golden-evidence")
    parser.add_argument("--immutable-retention-days", default="365")
    parser.add_argument("--poll-seconds", type=int, default=10)
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    parser.add_argument("--download-dir", default="dist/golden")
    parser.add_argument(
        "--allow-legacy-workflow",
        action="store_true",
        help="Allow dispatch when remote workflow lacks enterprise inputs like signing_mode.",
    )
    return parser


def _supported_workflow_inputs(repo: str, ref: str) -> set[str]:
    workflow_path = ".github/workflows/release-gate.yml"
    result = _run(
        [
            "gh",
            "api",
            f"repos/{repo}/contents/{workflow_path}?ref={ref}",
        ]
    )
    payload = json.loads(result.stdout)
    content = str(payload.get("content", ""))
    encoding = str(payload.get("encoding", ""))
    if not content or encoding != "base64":
        raise RuntimeError("Unable to read release-gate workflow file from remote repository.")
    workflow_yaml = base64.b64decode(content).decode("utf-8")
    workflow = yaml.safe_load(workflow_yaml)
    # PyYAML may resolve unquoted "on" key to boolean True (YAML 1.1 behavior).
    on_block = (
        workflow.get("on", workflow.get(True, {}))
        if isinstance(workflow, dict)
        else {}
    )
    dispatch_block = on_block.get("workflow_dispatch", {}) if isinstance(on_block, dict) else {}
    inputs_block = dispatch_block.get("inputs", {}) if isinstance(dispatch_block, dict) else {}
    return set(inputs_block.keys()) if isinstance(inputs_block, dict) else set()


def _dispatch(args: argparse.Namespace) -> None:
    requested_fields = {
        "case_path": args.case_path,
        "oracle_mode": args.oracle_mode,
        "signing_mode": args.signing_mode,
        "change_class": args.change_class,
        "ticket": args.ticket,
        "risk_statement": args.risk_statement,
        "author": args.author,
        "evidence_pack_id": args.evidence_pack_id,
        "kms_key_version": args.kms_key_version,
        "immutable_bucket": args.immutable_bucket,
        "immutable_prefix": args.immutable_prefix,
        "immutable_retention_days": args.immutable_retention_days,
    }
    supported_inputs = _supported_workflow_inputs(repo=args.repo, ref=args.ref)
    missing_enterprise_inputs = {"signing_mode", "immutable_bucket", "immutable_prefix", "immutable_retention_days"} - supported_inputs
    if missing_enterprise_inputs and not args.allow_legacy_workflow:
        missing = ", ".join(sorted(missing_enterprise_inputs))
        raise RuntimeError(
            "Remote release-gate workflow is missing enterprise inputs "
            f"({missing}). Push the latest .github/workflows/release-gate.yml and retry, "
            "or pass --allow-legacy-workflow."
        )

    fields = {key: value for key, value in requested_fields.items() if key in supported_inputs}
    skipped_fields = sorted(set(requested_fields.keys()) - set(fields.keys()))
    if skipped_fields:
        print(f"warning: remote workflow does not support inputs: {', '.join(skipped_fields)}")

    cmd = [
        "gh",
        "workflow",
        "run",
        "release-gate.yml",
        "--repo",
        args.repo,
        "--ref",
        args.ref,
    ]
    for key, value in fields.items():
        cmd.extend(["-f", f"{key}={value}"])
    result = _run(cmd)
    if result.stdout.strip():
        print(result.stdout.strip())


def _latest_release_gate_run(repo: str, ref: str) -> dict:
    result = _run(
        [
            "gh",
            "run",
            "list",
            "--repo",
            repo,
            "--workflow",
            "release-gate.yml",
            "--branch",
            ref,
            "--limit",
            "1",
            "--json",
            "databaseId,status,conclusion,url,createdAt",
        ]
    )
    payload = json.loads(result.stdout)
    if not payload:
        raise RuntimeError("No release-gate workflow runs found")
    return dict(payload[0])


def _latest_release_gate_run_after(repo: str, ref: str, created_after_epoch: float) -> dict | None:
    result = _run(
        [
            "gh",
            "run",
            "list",
            "--repo",
            repo,
            "--workflow",
            "release-gate.yml",
            "--branch",
            ref,
            "--limit",
            "20",
            "--json",
            "databaseId,status,conclusion,url,createdAt",
        ]
    )
    payload = json.loads(result.stdout)
    newest: dict | None = None
    newest_ts = float("-inf")
    for item in payload:
        created_at = str(item.get("createdAt", ""))
        if not created_at:
            continue
        try:
            ts = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp()
        except ValueError:
            continue
        if ts < created_after_epoch:
            continue
        if ts > newest_ts:
            newest = dict(item)
            newest_ts = ts
    return newest


def _print_failed_logs(repo: str, run_id: str) -> None:
    result = _run(
        [
            "gh",
            "run",
            "view",
            run_id,
            "--repo",
            repo,
            "--log-failed",
        ],
        check=False,
    )
    text = result.stdout.strip() or result.stderr.strip()
    if text:
        print("---- failed logs ----")
        print(text)
        print("---- end failed logs ----")


def main() -> int:
    args = _build_parser().parse_args()
    dispatch_started = time.time() - 1.0
    _dispatch(args)

    started = time.time()
    run: dict = {}
    while True:
        candidate = _latest_release_gate_run_after(
            repo=args.repo,
            ref=args.ref,
            created_after_epoch=dispatch_started,
        )
        if candidate is None:
            if time.time() - started > args.timeout_seconds:
                raise TimeoutError("Timed out waiting for release-gate run to appear")
            print("waiting for release-gate run creation...")
            time.sleep(args.poll_seconds)
            continue
        run = candidate
        status = str(run.get("status", ""))
        conclusion = str(run.get("conclusion", ""))
        print(f"release-gate run {run.get('databaseId')} status={status} conclusion={conclusion}")
        if status == "completed":
            break
        if time.time() - started > args.timeout_seconds:
            raise TimeoutError("Timed out waiting for release-gate run to complete")
        time.sleep(args.poll_seconds)

    run_id = str(run["databaseId"])
    if str(run.get("conclusion")) != "success":
        _print_failed_logs(repo=args.repo, run_id=run_id)
        raise RuntimeError(f"release-gate failed: {run.get('url')}")

    artifact_name = f"release-evidence-{args.evidence_pack_id}"
    output_dir = Path(args.download_dir).resolve() / args.evidence_pack_id
    output_dir.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "gh",
            "run",
            "download",
            run_id,
            "--repo",
            args.repo,
            "--name",
            artifact_name,
            "--dir",
            str(output_dir),
        ]
    )
    summary = {
        "repo": args.repo,
        "ref": args.ref,
        "run_id": run_id,
        "run_url": run.get("url"),
        "artifact_name": artifact_name,
        "artifact_dir": str(output_dir),
    }
    summary_path = output_dir / "golden_release_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"golden evidence downloaded: {output_dir}")
    print(f"summary: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
