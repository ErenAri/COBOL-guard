from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT_DIR = Path(__file__).resolve().parents[1]
TOOLS_DIR = ROOT_DIR / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import run_release_gate  # type: ignore[import-not-found]


def test_supported_workflow_inputs_handles_on_boolean_key(monkeypatch) -> None:
    workflow_yaml = """\
name: Release Gate
on:
  workflow_dispatch:
    inputs:
      case_path:
        required: true
      ticket:
        required: true
"""
    payload = {
        "content": base64.b64encode(workflow_yaml.encode("utf-8")).decode("ascii"),
        "encoding": "base64",
    }

    def fake_run(cmd: list[str], check: bool = True):
        del cmd, check
        return SimpleNamespace(stdout=json.dumps(payload), stderr="", returncode=0)

    monkeypatch.setattr(run_release_gate, "_run", fake_run)
    supported = run_release_gate._supported_workflow_inputs(repo="owner/repo", ref="main")
    assert supported == {"case_path", "ticket"}


def test_dispatch_only_sends_supported_fields(monkeypatch) -> None:
    monkeypatch.setattr(
        run_release_gate,
        "_supported_workflow_inputs",
        lambda repo, ref: {
            "ticket",
            "author",
            "signing_mode",
            "immutable_bucket",
            "immutable_prefix",
            "immutable_retention_days",
        },
    )
    captured: dict[str, list[str]] = {}

    def fake_run(cmd: list[str], check: bool = True):
        del check
        captured["cmd"] = cmd
        return SimpleNamespace(stdout="", stderr="", returncode=0)

    monkeypatch.setattr(run_release_gate, "_run", fake_run)
    args = argparse.Namespace(
        repo="owner/repo",
        ref="main",
        case_path="fixtures/cases/basic.yml",
        oracle_mode="cobol-executable",
        signing_mode="kms-command",
        change_class="bug_fix",
        ticket="CHG-1",
        risk_statement="risk",
        author="alice",
        evidence_pack_id="v0.1",
        kms_key_version="",
        immutable_bucket="",
        immutable_prefix="golden-evidence",
        immutable_retention_days="365",
        allow_legacy_workflow=False,
    )

    run_release_gate._dispatch(args)

    cmd = captured["cmd"]
    assert "-f" in cmd
    assert "ticket=CHG-1" in cmd
    assert "author=alice" in cmd
    assert "signing_mode=kms-command" in cmd
    assert "case_path=fixtures/cases/basic.yml" not in cmd


def test_dispatch_requires_enterprise_inputs_by_default(monkeypatch) -> None:
    monkeypatch.setattr(run_release_gate, "_supported_workflow_inputs", lambda repo, ref: {"ticket"})
    monkeypatch.setattr(run_release_gate, "_run", lambda cmd, check=True: SimpleNamespace(stdout="", stderr="", returncode=0))
    args = argparse.Namespace(
        repo="owner/repo",
        ref="main",
        case_path="fixtures/cases/basic.yml",
        oracle_mode="cobol-executable",
        signing_mode="kms-command",
        change_class="bug_fix",
        ticket="CHG-1",
        risk_statement="risk",
        author="alice",
        evidence_pack_id="v0.1",
        kms_key_version="",
        immutable_bucket="",
        immutable_prefix="golden-evidence",
        immutable_retention_days="365",
        allow_legacy_workflow=False,
    )

    try:
        run_release_gate._dispatch(args)
    except RuntimeError as exc:
        assert "missing enterprise inputs" in str(exc)
    else:
        raise AssertionError("expected RuntimeError when enterprise inputs are missing")
