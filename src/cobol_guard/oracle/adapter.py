from __future__ import annotations

import json
import os
import subprocess
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cobol_guard.command_templates import render_command_template
from cobol_guard.candidate.engine import EngineResult
from cobol_guard.contracts import ExceptionRecord, JournalRecord, ReconcileTotals, Transaction
from cobol_guard.io_utils import read_fixed_width_records
from cobol_guard.oracle.cobol_transport import (
    compile_cobol,
    run_cobol_executable,
    write_transactions_dat,
)
from cobol_guard.oracle.oracle_python_reference import run_reference_oracle
from cobol_guard.schema_registry import load_schema


@dataclass(slots=True)
class OracleAdapter:
    mode: str = "python-reference"
    command_template: str | None = None
    cobol_source: Path | None = None
    cobol_executable: Path | None = None

    @classmethod
    def from_environment(cls) -> "OracleAdapter":
        mode = os.environ.get("COBOL_GUARD_ORACLE_MODE", "python-reference")
        command_template = os.environ.get("COBOL_GUARD_ORACLE_COMMAND")
        executable = os.environ.get("COBOL_GUARD_ORACLE_EXECUTABLE")
        cobol_source = os.environ.get("COBOL_GUARD_COBOL_SOURCE", "programs/v1/LEDGER01.cbl")
        cobol_build_dir = os.environ.get("COBOL_GUARD_COBOL_BUILD_DIR", "build/cobol")
        cobol_exec_path = Path(cobol_build_dir) / ("LEDGER01.exe" if os.name == "nt" else "LEDGER01")
        if mode == "cobol-executable" and not command_template and executable:
            command_template = f"\"{executable}\" --input \"{{input_jsonl}}\" --output \"{{output_json}}\" --business-date \"{{business_date}}\""
        return cls(
            mode=mode,
            command_template=command_template,
            cobol_source=Path(cobol_source),
            cobol_executable=cobol_exec_path,
        )

    def _run_cobol_command_mode(self, transactions: Iterable[Transaction], business_date: str) -> EngineResult:
        if not self.command_template:
            raise RuntimeError(
                "COBOL command mode requires COBOL_GUARD_ORACLE_COMMAND or COBOL_GUARD_ORACLE_EXECUTABLE."
            )
        transactions_payload = [txn.to_dict() for txn in transactions]
        with tempfile.TemporaryDirectory(prefix="cobol-guard-oracle-") as work_dir_text:
            work_dir = Path(work_dir_text)
            input_jsonl = work_dir / "oracle_input_transactions.jsonl"
            output_json = work_dir / "oracle_result.json"
            with input_jsonl.open("w", encoding="utf-8", newline="\n") as handle:
                for row in transactions_payload:
                    handle.write(json.dumps(row, sort_keys=True) + "\n")

            command = render_command_template(
                self.command_template,
                required_fields={"input_jsonl", "output_json", "business_date"},
                optional_fields={"work_dir"},
                values={
                    "input_jsonl": str(input_jsonl),
                    "output_json": str(output_json),
                    "business_date": business_date,
                    "work_dir": str(work_dir),
                },
            )
            completed = subprocess.run(command, shell=True, capture_output=True, text=True)
            if completed.returncode != 0:
                raise RuntimeError(
                    "COBOL oracle command failed "
                    f"(exit={completed.returncode}): stdout={completed.stdout.strip()} stderr={completed.stderr.strip()}"
                )
            if not output_json.exists():
                raise RuntimeError(f"COBOL oracle command did not produce expected output file: {output_json}")

            payload = json.loads(output_json.read_text(encoding="utf-8"))
            return self._decode_engine_result(payload=payload)

    @staticmethod
    def _decode_engine_result(payload: dict[str, Any]) -> EngineResult:
        return EngineResult(
            journal=[JournalRecord(**item) for item in payload.get("journal", [])],
            exceptions=[ExceptionRecord(**item) for item in payload.get("exceptions", [])],
            totals=ReconcileTotals(**payload["totals"]),
        )

    def _run_cobol_executable_mode(self, transactions: Iterable[Transaction], business_date: str) -> EngineResult:
        if self.cobol_source is None or self.cobol_executable is None:
            raise RuntimeError("COBOL source/executable paths are not configured.")

        source = self.cobol_source.resolve()
        executable = self.cobol_executable.resolve()
        if (not executable.exists()) or (source.exists() and source.stat().st_mtime > executable.stat().st_mtime):
            compile_cobol(source=source, output_executable=executable)

        with tempfile.TemporaryDirectory(prefix="cobol-guard-exec-") as work_dir_text:
            work_dir = Path(work_dir_text)
            in_path = work_dir / "transactions.dat"
            write_transactions_dat(path=in_path, transactions=list(transactions))
            run_cobol_executable(executable=executable, working_dir=work_dir)

            journal_schema = load_schema("ledger_journal", version_hint="1")
            totals_schema = load_schema("reconcile_totals", version_hint="1")
            exceptions_schema = load_schema("exception_report", version_hint="1")

            journal_rows = read_fixed_width_records(path=work_dir / "ledger_journal.dat", schema=journal_schema)
            totals_rows = read_fixed_width_records(path=work_dir / "reconcile_totals.dat", schema=totals_schema)
            exception_rows = read_fixed_width_records(path=work_dir / "exception_report.dat", schema=exceptions_schema)
            if not totals_rows:
                raise RuntimeError("COBOL executable did not produce reconcile_totals.dat")

            return EngineResult(
                journal=[JournalRecord(**row) for row in journal_rows],
                exceptions=[ExceptionRecord(**row) for row in exception_rows],
                totals=ReconcileTotals(**totals_rows[0]),
            )

    def run(self, transactions: Iterable[Transaction], business_date: str) -> EngineResult:
        if self.mode == "python-reference":
            return run_reference_oracle(transactions=transactions, business_date=business_date)
        if self.mode == "cobol-command":
            return self._run_cobol_command_mode(transactions=transactions, business_date=business_date)
        if self.mode == "cobol-executable":
            return self._run_cobol_executable_mode(transactions=transactions, business_date=business_date)
        raise RuntimeError(f"Unsupported oracle mode: {self.mode}")
