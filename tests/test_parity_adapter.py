import json
from pathlib import Path

from cobol_guard.candidate.engine import LedgerEngine
from cobol_guard.contracts import Transaction
from cobol_guard.harness.diff_engine import diff_runs
from cobol_guard.harness.run_engine import execute_case
from cobol_guard.io_utils import read_fixed_width_records, write_fixed_width_records
from cobol_guard.oracle.adapter import OracleAdapter
from cobol_guard.schema_registry import load_schema


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


def test_adapter_output_round_trip_uses_schema_canonicalization(tmp_path: Path) -> None:
    case_path = Path("fixtures/cases/basic.yml")
    oracle_dir = execute_case(target="oracle", case_path=case_path, version="v1", out_root=tmp_path)

    artifacts = {
        "ledger_journal.dat": "ledger_journal",
        "reconcile_totals.dat": "reconcile_totals",
        "exception_report.dat": "exception_report",
    }
    for artifact, schema_id in artifacts.items():
        schema = load_schema(schema_id=schema_id, version_hint="1")
        source = read_fixed_width_records(path=oracle_dir / artifact, schema=schema)
        round_trip_path = tmp_path / "roundtrip" / artifact
        write_fixed_width_records(path=round_trip_path, records=source, schema=schema)
        round_trip = read_fixed_width_records(path=round_trip_path, schema=schema)
        assert round_trip == source


def test_adapter_reverse_request_id_mapping_matches_candidate() -> None:
    business_date = "20260110"
    transactions = [
        Transaction(
            request_id="REQ000000000001",
            operation="POST",
            original_request_id="",
            account_id="ACC000000001",
            amount_cents=5000,
            business_date=business_date,
            event_time="20260110100000",
        ),
        Transaction(
            request_id="REV000000000001",
            operation="REVERSE",
            original_request_id="REQ000000000001",
            account_id="ACC000000001",
            amount_cents=0,
            business_date=business_date,
            event_time="20260110100100",
        ),
        Transaction(
            request_id="REV000000000001",
            operation="REVERSE",
            original_request_id="REQ000000000001",
            account_id="ACC000000001",
            amount_cents=0,
            business_date=business_date,
            event_time="20260110100200",
        ),
        Transaction(
            request_id="REV000000000002",
            operation="REVERSE",
            original_request_id="REQ000000000001",
            account_id="ACC000000001",
            amount_cents=0,
            business_date=business_date,
            event_time="20260110100300",
        ),
    ]

    oracle = OracleAdapter(mode="python-reference")
    oracle_result = oracle.run(transactions=transactions, business_date=business_date)
    v2_result = LedgerEngine().process(transactions=transactions, business_date=business_date)

    oracle_reverse = [
        (row.request_id, row.original_request_id, row.status, row.audit_event, row.amount_cents)
        for row in oracle_result.journal
        if row.operation == "REVERSE"
    ]
    v2_reverse = [
        (row.request_id, row.original_request_id, row.status, row.audit_event, row.amount_cents)
        for row in v2_result.journal
        if row.operation == "REVERSE"
    ]
    assert oracle_reverse == v2_reverse
    assert [row[2] for row in v2_reverse] == ["APPLIED", "DUPLICATE_IGNORED", "ORIG_ALREADY_REVERSED"]
