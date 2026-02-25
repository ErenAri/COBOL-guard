from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from cobol_guard.batch.checkpoint import CheckpointManager
from cobol_guard.candidate.engine import LedgerEngine
from cobol_guard.contracts import Transaction
from cobol_guard.io_utils import write_fixed_width_records
from cobol_guard.schema_registry import SchemaDefinition, load_schema


@dataclass(slots=True)
class BatchRunMetadata:
    chunk_count: int
    processed_chunks: int
    skipped_chunks: int
    reworked_chunks: int
    checkpoint_file: str
    restart_mode: bool

    def to_dict(self) -> dict:
        return {
            "chunk_count": self.chunk_count,
            "processed_chunks": self.processed_chunks,
            "skipped_chunks": self.skipped_chunks,
            "reworked_chunks": self.reworked_chunks,
            "checkpoint_file": self.checkpoint_file,
            "restart_mode": self.restart_mode,
        }


def _chunk_id(index: int) -> str:
    return f"{index:06d}"


def _atomic_write_text(path: Path, text: str) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path.write_text(text, encoding="utf-8", newline="\n")
    tmp_path.replace(path)


def _atomic_write_fixed_width(path: Path, records: list[dict], schema: SchemaDefinition) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    write_fixed_width_records(path=tmp_path, records=records, schema=schema)
    tmp_path.replace(path)


def _hash_chunk_input(transactions: list[Transaction]) -> str:
    hasher = hashlib.sha256()
    for txn in transactions:
        payload = json.dumps(txn.to_dict(), sort_keys=True, separators=(",", ":"))
        hasher.update(payload.encode("utf-8"))
    return hasher.hexdigest()


def _chunks(transactions: list[Transaction], chunk_size: int) -> list[list[Transaction]]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    return [transactions[i : i + chunk_size] for i in range(0, len(transactions), chunk_size)]


def _finalize_outputs(run_id: str, business_date: str, run_dir: Path, checkpoint_manager: CheckpointManager) -> None:
    committed_ids = checkpoint_manager.committed_chunk_ids(run_id=run_id)
    journal_out = run_dir / "ledger_journal.dat"
    exceptions_out = run_dir / "exception_report.dat"

    journal_tmp = journal_out.with_suffix(".dat.tmp")
    exceptions_tmp = exceptions_out.with_suffix(".dat.tmp")
    journal_tmp.parent.mkdir(parents=True, exist_ok=True)
    with journal_tmp.open("w", encoding="utf-8", newline="\n") as journal_handle:
        with exceptions_tmp.open("w", encoding="utf-8", newline="\n") as exceptions_handle:
            total_post_cents = 0
            total_reverse_cents = 0
            records_processed = 0
            applied_records = 0
            exception_count = 0
            closing_total_cents = 0
            for chunk_id in committed_ids:
                chunk_dir = run_dir / "chunks" / chunk_id
                chunk_manifest_path = chunk_dir / "chunk_manifest.json"
                if not chunk_manifest_path.exists():
                    raise RuntimeError(f"Committed chunk missing manifest: {chunk_manifest_path}")
                chunk_manifest = json.loads(chunk_manifest_path.read_text(encoding="utf-8"))

                journal_path = chunk_dir / "ledger_journal.dat"
                exceptions_path = chunk_dir / "exception_report.dat"
                if journal_path.exists():
                    journal_handle.write(journal_path.read_text(encoding="utf-8"))
                if exceptions_path.exists():
                    exceptions_handle.write(exceptions_path.read_text(encoding="utf-8"))

                totals = chunk_manifest["chunk_totals"]
                total_post_cents += int(totals["total_post_cents"])
                total_reverse_cents += int(totals["total_reverse_cents"])
                records_processed += int(totals["records_processed"])
                applied_records += int(totals["applied_records"])
                exception_count += int(totals["exception_count"])
                closing_total_cents = int(totals["closing_total_cents_after_chunk"])

    journal_tmp.replace(journal_out)
    exceptions_tmp.replace(exceptions_out)

    totals_schema = load_schema("reconcile_totals", version_hint="1")
    totals_record = {
        "business_date": business_date,
        "total_post_cents": total_post_cents if committed_ids else 0,
        "total_reverse_cents": total_reverse_cents if committed_ids else 0,
        "net_delta_cents": (total_post_cents - total_reverse_cents) if committed_ids else 0,
        "closing_total_cents": closing_total_cents if committed_ids else 0,
        "records_processed": records_processed if committed_ids else 0,
        "applied_records": applied_records if committed_ids else 0,
        "exception_count": exception_count if committed_ids else 0,
    }
    write_fixed_width_records(
        path=run_dir / "reconcile_totals.dat",
        records=[totals_record],
        schema=totals_schema,
    )


def execute_checkpointed_v2_batch(
    run_id: str,
    business_date: str,
    transactions: list[Transaction],
    run_dir: Path,
    chunk_size: int,
    resume: bool,
    fail_after_chunks: int | None = None,
) -> BatchRunMetadata:
    checkpoint_manager = CheckpointManager(state_root=run_dir / "checkpoints")
    checkpoint_manager.ensure(run_id=run_id, target="v2", chunk_size=chunk_size)
    engine = LedgerEngine()
    engine.load_state(checkpoint_manager.get_engine_state(run_id=run_id))

    chunks = _chunks(transactions=transactions, chunk_size=chunk_size)
    processed_chunks = 0
    skipped_chunks = 0
    reworked_chunks = 0
    journal_schema = load_schema("ledger_journal", version_hint="1")
    exceptions_schema = load_schema("exception_report", version_hint="1")

    for chunk_index, chunk in enumerate(chunks):
        chunk_id = _chunk_id(chunk_index)
        if checkpoint_manager.is_chunk_committed(run_id=run_id, chunk_id=chunk_id):
            skipped_chunks += 1
            continue

        chunk_dir = run_dir / "chunks" / chunk_id
        chunk_dir.mkdir(parents=True, exist_ok=True)
        inflight_path = chunk_dir / "inflight.marker"
        if inflight_path.exists():
            reworked_chunks += 1
        _atomic_write_text(path=inflight_path, text="inflight\n")

        chunk_result = engine.process(transactions=chunk, business_date=business_date)

        _atomic_write_fixed_width(
            path=chunk_dir / "ledger_journal.dat",
            records=[item.to_dict() for item in chunk_result.journal],
            schema=journal_schema,
        )
        _atomic_write_fixed_width(
            path=chunk_dir / "exception_report.dat",
            records=[item.to_dict() for item in chunk_result.exceptions],
            schema=exceptions_schema,
        )
        chunk_manifest = {
            "chunk_id": chunk_id,
            "chunk_index": chunk_index,
            "input_fingerprint": _hash_chunk_input(transactions=chunk),
            "last_unit_of_work": (
                f"{chunk[-1].account_id}:{business_date}" if chunk else f"NONE:{business_date}"
            ),
            "chunk_totals": {
                "total_post_cents": chunk_result.totals.total_post_cents,
                "total_reverse_cents": chunk_result.totals.total_reverse_cents,
                "records_processed": chunk_result.totals.records_processed,
                "applied_records": chunk_result.totals.applied_records,
                "exception_count": chunk_result.totals.exception_count,
                "closing_total_cents_after_chunk": chunk_result.totals.closing_total_cents,
            },
        }
        _atomic_write_text(
            path=chunk_dir / "chunk_manifest.json",
            text=json.dumps(chunk_manifest, indent=2, sort_keys=True) + "\n",
        )

        processed_chunks += 1
        if fail_after_chunks is not None and processed_chunks >= fail_after_chunks:
            raise RuntimeError(f"simulated_failure_after_chunks={fail_after_chunks}")

        checkpoint_manager.mark_chunk_committed(
            run_id=run_id,
            chunk_id=chunk_id,
            last_unit_of_work=str(chunk_manifest["last_unit_of_work"]),
            input_fingerprint=str(chunk_manifest["input_fingerprint"]),
            chunk_index=chunk_index,
            chunk_manifest=chunk_manifest,
            engine_state=engine.snapshot_state(),
        )
        inflight_path.unlink(missing_ok=True)

    _finalize_outputs(run_id=run_id, business_date=business_date, run_dir=run_dir, checkpoint_manager=checkpoint_manager)
    return BatchRunMetadata(
        chunk_count=len(chunks),
        processed_chunks=processed_chunks,
        skipped_chunks=skipped_chunks,
        reworked_chunks=reworked_chunks,
        checkpoint_file=str((run_dir / "checkpoints" / f"{run_id}.checkpoint.json")),
        restart_mode=resume,
    )
