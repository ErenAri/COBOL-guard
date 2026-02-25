from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from cobol_guard.batch.runner import BatchRunMetadata, execute_checkpointed_v2_batch
from cobol_guard.candidate.engine import LedgerEngine
from cobol_guard.constants import REPO_ROOT, RUNS_DIR
from cobol_guard.contracts import Transaction
from cobol_guard.io_utils import read_jsonl, write_fixed_width_records, write_json
from cobol_guard.oracle.adapter import OracleAdapter
from cobol_guard.schema_registry import load_schema

ARTIFACT_SCHEMA_MAP: dict[str, str] = {
    "ledger_journal.dat": "ledger_journal",
    "reconcile_totals.dat": "reconcile_totals",
    "exception_report.dat": "exception_report",
}


@dataclass(slots=True)
class CaseSpec:
    case_id: str
    business_date: str
    seed_id: str
    benchmark_profile_id: str
    transactions_path: Path
    chunk_size: int


def load_case(case_path: Path) -> CaseSpec:
    payload = yaml.safe_load(case_path.read_text(encoding="utf-8"))
    tx_path = Path(payload["transactions_path"])
    if not tx_path.is_absolute():
        tx_path = (REPO_ROOT / tx_path).resolve()
    return CaseSpec(
        case_id=str(payload["case_id"]),
        business_date=str(payload["business_date"]),
        seed_id=str(payload["seed_id"]),
        benchmark_profile_id=str(payload["benchmark_profile_id"]),
        transactions_path=tx_path,
        chunk_size=int(payload.get("chunk_size", 1000)),
    )


def load_transactions(transactions_path: Path) -> list[Transaction]:
    return [Transaction.from_dict(item) for item in read_jsonl(path=transactions_path)]


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _run_target(target: str, transactions: list[Transaction], business_date: str):
    if target == "oracle":
        adapter = OracleAdapter.from_environment()
        return adapter.run(transactions=transactions, business_date=business_date)
    if target == "v2":
        return LedgerEngine().process(transactions=transactions, business_date=business_date)
    raise ValueError(f"Unsupported target: {target}")


def execute_case(
    target: str,
    case_path: Path,
    version: str,
    deterministic: bool = True,
    out_root: Path | None = None,
    run_id: str | None = None,
    resume: bool = False,
    fail_after_chunks: int | None = None,
    chunk_size_override: int | None = None,
) -> Path:
    case = load_case(case_path=case_path)
    transactions = load_transactions(transactions_path=case.transactions_path)

    root = out_root or RUNS_DIR
    effective_run_id = run_id or f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_{case.case_id}_{target}_{uuid4().hex[:8]}"
    run_dir = root / effective_run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    batch_metadata: BatchRunMetadata | None = None

    if target == "v2":
        chunk_size = int(chunk_size_override or case.chunk_size)
        batch_metadata = execute_checkpointed_v2_batch(
            run_id=effective_run_id,
            business_date=case.business_date,
            transactions=transactions,
            run_dir=run_dir,
            chunk_size=chunk_size,
            resume=resume,
            fail_after_chunks=fail_after_chunks,
        )
    else:
        result = _run_target(target=target, transactions=transactions, business_date=case.business_date)
        journal_schema = load_schema("ledger_journal", version_hint="1")
        totals_schema = load_schema("reconcile_totals", version_hint="1")
        exceptions_schema = load_schema("exception_report", version_hint="1")

        write_fixed_width_records(
            path=run_dir / "ledger_journal.dat",
            records=[item.to_dict() for item in result.journal],
            schema=journal_schema,
        )
        write_fixed_width_records(
            path=run_dir / "reconcile_totals.dat",
            records=[result.totals.to_dict()],
            schema=totals_schema,
        )
        write_fixed_width_records(
            path=run_dir / "exception_report.dat",
            records=[item.to_dict() for item in result.exceptions],
            schema=exceptions_schema,
        )

    artifact_hashes = {
        artifact: _sha256_file(run_dir / artifact)
        for artifact in ARTIFACT_SCHEMA_MAP
        if (run_dir / artifact).exists()
    }
    manifest = {
        "run_id": effective_run_id,
        "case_id": case.case_id,
        "target": target,
        "version": version,
        "business_date": case.business_date,
        "seed_id": case.seed_id,
        "benchmark_profile_id": case.benchmark_profile_id,
        "deterministic_mode": deterministic,
        "resume_mode": resume,
        "chunk_size": int(chunk_size_override or case.chunk_size),
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "schema_versions": {
            "ledger_journal": "1.0.0",
            "reconcile_totals": "1.0.0",
            "exception_report": "1.0.0",
        },
        "artifact_hashes": artifact_hashes,
        "batch_restart": batch_metadata.to_dict() if batch_metadata else None,
    }
    write_json(path=run_dir / "run_manifest.json", payload=manifest)
    case_snapshot = asdict(case)
    case_snapshot["transactions_path"] = str(case.transactions_path)
    write_json(path=run_dir / "case_snapshot.json", payload=case_snapshot)
    return run_dir
