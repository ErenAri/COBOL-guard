import json
from pathlib import Path

import pytest

from cobol_guard.harness.diff_engine import diff_runs
from cobol_guard.harness.run_engine import execute_case


def test_adversarial_restart_resume_and_parity(tmp_path: Path) -> None:
    case_path = Path("fixtures/cases/adversarial_restart.yml")
    run_id = "adversarial-restart-run"

    with pytest.raises(RuntimeError):
        execute_case(
            target="v2",
            case_path=case_path,
            version="v2",
            out_root=tmp_path,
            run_id=run_id,
            fail_after_chunks=2,
        )

    resumed_dir = execute_case(
        target="v2",
        case_path=case_path,
        version="v2",
        out_root=tmp_path,
        run_id=run_id,
        resume=True,
    )
    manifest = json.loads((resumed_dir / "run_manifest.json").read_text(encoding="utf-8"))
    restart = manifest["batch_restart"]
    assert restart["restart_mode"] is True
    assert restart["chunk_count"] >= 5
    assert restart["reworked_chunks"] >= 1
    assert restart["reworked_chunks"] <= 1

    oracle_dir = execute_case(target="oracle", case_path=case_path, version="v1", out_root=tmp_path)
    report = diff_runs(baseline_dir=oracle_dir, candidate_dir=resumed_dir)
    assert report.changed_records == 0
