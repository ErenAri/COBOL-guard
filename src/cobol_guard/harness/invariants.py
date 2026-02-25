from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cobol_guard.io_utils import read_fixed_width_records
from cobol_guard.schema_registry import load_schema


@dataclass(slots=True)
class InvariantResult:
    invariant_id: str
    passed: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "invariant_id": self.invariant_id,
            "passed": self.passed,
            "detail": self.detail,
        }


def evaluate_invariants(run_dir: Path) -> list[InvariantResult]:
    journal_schema = load_schema("ledger_journal", version_hint="1")
    totals_schema = load_schema("reconcile_totals", version_hint="1")
    journal = read_fixed_width_records(path=run_dir / "ledger_journal.dat", schema=journal_schema)
    totals = read_fixed_width_records(path=run_dir / "reconcile_totals.dat", schema=totals_schema)
    totals_record: dict[str, Any] = totals[0] if totals else {}

    applied_post_sum = sum(
        int(row["amount_cents"])
        for row in journal
        if row["status"] == "APPLIED" and row["operation"] == "POST"
    )
    applied_reverse_sum = sum(
        abs(int(row["amount_cents"]))
        for row in journal
        if row["status"] == "APPLIED" and row["operation"] == "REVERSE"
    )
    computed_net = applied_post_sum - applied_reverse_sum
    closing_total = int(totals_record.get("closing_total_cents", 0))
    reported_net = int(totals_record.get("net_delta_cents", 0))

    duplicates_have_zero_effect = all(
        int(row["amount_cents"]) == 0
        for row in journal
        if row["status"] == "DUPLICATE_IGNORED"
    )

    reverse_refs: dict[str, int] = {}
    for row in journal:
        if row["operation"] == "POST" and row["status"] == "APPLIED":
            reverse_refs[str(row["request_id"])] = int(row["amount_cents"])

    reversal_ok = True
    for row in journal:
        if row["operation"] != "REVERSE" or row["status"] != "APPLIED":
            continue
        original_request_id = str(row["original_request_id"]).strip()
        if original_request_id not in reverse_refs:
            reversal_ok = False
            break
        if abs(int(row["amount_cents"])) != reverse_refs[original_request_id]:
            reversal_ok = False
            break

    return [
        InvariantResult(
            invariant_id="conservation",
            passed=(computed_net == reported_net == closing_total),
            detail=f"computed_net={computed_net} reported_net={reported_net} closing_total={closing_total}",
        ),
        InvariantResult(
            invariant_id="idempotency_no_effect",
            passed=duplicates_have_zero_effect,
            detail="all DUPLICATE_IGNORED rows had zero amount effect",
        ),
        InvariantResult(
            invariant_id="reversal_references_valid_post",
            passed=reversal_ok,
            detail="each APPLIED REVERSE references APPLIED POST with equal magnitude",
        ),
        InvariantResult(
            invariant_id="reconcile_consistency",
            passed=(reported_net == int(totals_record.get("total_post_cents", 0)) - int(totals_record.get("total_reverse_cents", 0))),
            detail="reported net equals total_post - total_reverse",
        ),
    ]
