from __future__ import annotations

from pathlib import Path

import pytest

from cobol_guard.contracts import Transaction
from cobol_guard.io_utils import write_fixed_width_records
from cobol_guard.oracle import adapter as adapter_module
from cobol_guard.oracle.adapter import OracleAdapter
from cobol_guard.schema_registry import load_schema


def test_oracle_executable_mode_uses_cobol_outputs(monkeypatch, tmp_path: Path) -> None:
    source_path = tmp_path / "LEDGER01.cbl"
    source_path.write_text("IDENTIFICATION DIVISION.\nPROGRAM-ID. LEDGER01.\n", encoding="utf-8")
    build_dir = tmp_path / "build"
    executable = build_dir / "LEDGER01.exe"

    monkeypatch.setenv("COBOL_GUARD_ORACLE_MODE", "cobol-executable")
    monkeypatch.setenv("COBOL_GUARD_COBOL_SOURCE", str(source_path))
    monkeypatch.setenv("COBOL_GUARD_COBOL_BUILD_DIR", str(build_dir))

    def fake_compile(source: Path, output_executable: Path) -> None:
        output_executable.parent.mkdir(parents=True, exist_ok=True)
        output_executable.write_text("fake", encoding="utf-8")

    def fake_run(executable: Path, working_dir: Path) -> None:
        journal_schema = load_schema("ledger_journal", version_hint="1")
        totals_schema = load_schema("reconcile_totals", version_hint="1")
        exceptions_schema = load_schema("exception_report", version_hint="1")

        write_fixed_width_records(
            path=working_dir / "ledger_journal.dat",
            records=[
                {
                    "sequence_no": 1,
                    "business_date": "20260110",
                    "account_id": "ACC000000001",
                    "request_id": "REQ000000000001",
                    "operation": "POST",
                    "original_request_id": "",
                    "amount_cents": 15000,
                    "balance_before_cents": 0,
                    "balance_after_cents": 15000,
                    "status": "APPLIED",
                    "audit_event": "POST_APPLIED",
                }
            ],
            schema=journal_schema,
        )
        write_fixed_width_records(
            path=working_dir / "reconcile_totals.dat",
            records=[
                {
                    "business_date": "20260110",
                    "total_post_cents": 15000,
                    "total_reverse_cents": 0,
                    "net_delta_cents": 15000,
                    "closing_total_cents": 15000,
                    "records_processed": 1,
                    "applied_records": 1,
                    "exception_count": 0,
                }
            ],
            schema=totals_schema,
        )
        write_fixed_width_records(
            path=working_dir / "exception_report.dat",
            records=[],
            schema=exceptions_schema,
        )

    monkeypatch.setattr(adapter_module, "compile_cobol", fake_compile)
    monkeypatch.setattr(adapter_module, "run_cobol_executable", fake_run)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("run_reference_oracle should not be called in cobol-executable mode")

    monkeypatch.setattr(adapter_module, "run_reference_oracle", fail_if_called)

    adapter = OracleAdapter.from_environment()
    transactions = [
        Transaction(
            request_id="REQ000000000001",
            operation="POST",
            original_request_id="",
            account_id="ACC000000001",
            amount_cents=15000,
            business_date="20260110",
            event_time="20260110100000",
        )
    ]
    result = adapter.run(transactions=transactions, business_date="20260110")
    assert len(result.journal) == 1
    assert result.totals.total_post_cents == 15000
    assert result.totals.closing_total_cents == 15000
