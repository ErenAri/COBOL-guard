import json
from pathlib import Path

import pytest

from cobol_guard.harness.run_engine import execute_case


def test_checkpoint_resume_reworks_inflight_chunk(tmp_path: Path) -> None:
    case_path = Path("fixtures/cases/basic.yml")
    run_id = "resume_case_v2"
    with pytest.raises(RuntimeError):
        execute_case(
            target="v2",
            case_path=case_path,
            version="v2",
            out_root=tmp_path,
            run_id=run_id,
            fail_after_chunks=1,
        )

    run_dir = execute_case(
        target="v2",
        case_path=case_path,
        version="v2",
        out_root=tmp_path,
        run_id=run_id,
        resume=True,
    )
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    restart = manifest["batch_restart"]
    assert restart["restart_mode"] is True
    assert restart["reworked_chunks"] >= 1
    assert (run_dir / "ledger_journal.dat").exists()
    assert (run_dir / "reconcile_totals.dat").exists()
    assert (run_dir / "exception_report.dat").exists()
