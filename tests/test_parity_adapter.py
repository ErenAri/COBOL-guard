import json
from pathlib import Path

from cobol_guard.harness.diff_engine import diff_runs
from cobol_guard.harness.run_engine import execute_case


def test_adapter_parity_and_schema_binding(tmp_path: Path) -> None:
    case_path = Path("fixtures/cases/basic.yml")
    oracle_dir = execute_case(target="oracle", case_path=case_path, version="v1", out_root=tmp_path)
    v2_dir = execute_case(target="v2", case_path=case_path, version="v2", out_root=tmp_path)
    report = diff_runs(baseline_dir=oracle_dir, candidate_dir=v2_dir)
    assert report.changed_records == 0

    oracle_manifest = json.loads((oracle_dir / "run_manifest.json").read_text(encoding="utf-8"))
    v2_manifest = json.loads((v2_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert oracle_manifest["schema_versions"] == v2_manifest["schema_versions"]
    assert oracle_manifest["schema_versions"]["ledger_journal"] == "1.0.0"
