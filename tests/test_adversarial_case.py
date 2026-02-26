from pathlib import Path

from cobol_guard.governance.policy import evaluate_gate, load_policy
from cobol_guard.harness.diff_engine import diff_runs
from cobol_guard.harness.run_engine import execute_case
from cobol_guard.io_utils import read_fixed_width_records, write_fixed_width_records
from cobol_guard.schema_registry import load_schema


def test_adversarial_case_parity_and_exception_coverage(tmp_path: Path) -> None:
    case_path = Path("fixtures/cases/adversarial.yml")
    oracle_dir = execute_case(target="oracle", case_path=case_path, version="v1", out_root=tmp_path)
    v2_dir = execute_case(target="v2", case_path=case_path, version="v2", out_root=tmp_path)

    report = diff_runs(baseline_dir=oracle_dir, candidate_dir=v2_dir)
    assert report.changed_records == 0

    exception_schema = load_schema("exception_report", version_hint="1")
    journal_schema = load_schema("ledger_journal", version_hint="1")
    exceptions = read_fixed_width_records(path=oracle_dir / "exception_report.dat", schema=exception_schema)
    journal = read_fixed_width_records(path=oracle_dir / "ledger_journal.dat", schema=journal_schema)

    expected_codes = {
        "ORIG_NOT_FOUND",
        "ORIG_ALREADY_REVERSE",
        "ACCOUNT_MISMATCH",
        "BAD_OPERATION",
        "BUSINESS_DATE_MISMAT",
    }
    observed_codes = {str(item["error_code"]) for item in exceptions}
    assert expected_codes.issubset(observed_codes)
    observed_statuses = {str(item["status"]) for item in journal}
    assert "DUPLICATE_IGNORED" in observed_statuses
    assert "APPLIED" in observed_statuses


def test_adversarial_case_tamper_triggers_blocker_gate(tmp_path: Path) -> None:
    case_path = Path("fixtures/cases/adversarial.yml")
    oracle_dir = execute_case(target="oracle", case_path=case_path, version="v1", out_root=tmp_path)
    v2_dir = execute_case(target="v2", case_path=case_path, version="v2", out_root=tmp_path)

    journal_schema = load_schema("ledger_journal", version_hint="1")
    candidate_journal = read_fixed_width_records(path=v2_dir / "ledger_journal.dat", schema=journal_schema)
    target_index = next(index for index, row in enumerate(candidate_journal) if int(row["amount_cents"]) != 0)
    candidate_journal[target_index]["amount_cents"] = int(candidate_journal[target_index]["amount_cents"]) + 1
    write_fixed_width_records(path=v2_dir / "ledger_journal.dat", records=candidate_journal, schema=journal_schema)

    report = diff_runs(baseline_dir=oracle_dir, candidate_dir=v2_dir)
    policy = load_policy(Path("governance/gate_policy.yml"))
    decision = evaluate_gate(
        changed_records_ratio=report.changed_records_ratio,
        changed_fields=report.changed_fields,
        changed_conditions=report.changed_conditions,
        invariant_failures=[],
        policy=policy,
        change_class="intended_behavior_change",
    )

    assert not decision.passed
    assert "BLOCKER:amount_cents" in decision.blockers
