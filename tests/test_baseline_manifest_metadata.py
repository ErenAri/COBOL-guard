import json
from types import SimpleNamespace
from pathlib import Path

from cobol_guard.harness.cli import cmd_bless


def test_bless_includes_enterprise_manifest_metadata(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_RUN_ID", "22455430536")
    monkeypatch.setenv("COBOL_GUARD_WORKFLOW_RUN_ID", "123456")
    monkeypatch.setenv("COBOL_GUARD_ENVIRONMENT", "staging")
    monkeypatch.setenv("COBOL_GUARD_PROVENANCE_REF", "gha://run/123456")
    monkeypatch.setenv("COBOL_GUARD_SIGNING_MODE", "kms-command")
    monkeypatch.setenv("COBOL_GUARD_KMS_KEY_VERSION", "aws-kms/1")

    args = SimpleNamespace(
        baseline="candidate",
        target="oracle",
        case="fixtures/cases/basic.yml",
        version=None,
        change_class="bug_fix",
        ticket="REL-100",
        risk_statement="production evidence",
        author="release-bot",
        out_root=str(tmp_path / "runs"),
        baselines_root=str(tmp_path / "baselines"),
        policy=None,
        chunk_size=None,
    )
    exit_code = cmd_bless(args)
    assert exit_code == 0

    manifest_path = tmp_path / "baselines" / "candidate" / "basic" / "baseline_manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert payload["policy_version"] == "1"
    assert len(str(payload["policy_sha256"])) == 64
    assert payload["workflow_run_id"] == "123456"
    assert payload["environment"] == "staging"
    assert payload["provenance_ref"] == "gha://run/123456"
    assert payload["signing_mode"] == "kms-command"
    assert payload["kms_key_version"] == "aws-kms/1"
    assert str(payload["source_run_id"]).strip()
    assert str(payload["source_run_generated_at_utc"]).strip()
