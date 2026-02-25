from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from cobol_guard.contracts import ExceptionRecord, JournalRecord, ReconcileTotals, Transaction


@dataclass(slots=True)
class EngineResult:
    journal: list[JournalRecord]
    exceptions: list[ExceptionRecord]
    totals: ReconcileTotals


class LedgerEngine:
    def __init__(self) -> None:
        self._balances: dict[str, int] = {}
        self._processed_request_ids: set[str] = set()
        self._posting_request_ids: set[str] = set()
        self._posting_amount_by_request: dict[str, int] = {}
        self._posting_account_by_request: dict[str, str] = {}
        self._reversed_original_ids: set[str] = set()
        self._next_sequence_no = 1

    def snapshot_state(self) -> dict:
        return {
            "balances": dict(self._balances),
            "processed_request_ids": sorted(self._processed_request_ids),
            "posting_request_ids": sorted(self._posting_request_ids),
            "posting_amount_by_request": dict(self._posting_amount_by_request),
            "posting_account_by_request": dict(self._posting_account_by_request),
            "reversed_original_ids": sorted(self._reversed_original_ids),
            "next_sequence_no": self._next_sequence_no,
        }

    def load_state(self, state: dict | None) -> None:
        state = state or {}
        self._balances = {str(k): int(v) for k, v in dict(state.get("balances", {})).items()}
        self._processed_request_ids = {str(item) for item in state.get("processed_request_ids", [])}
        self._posting_request_ids = {str(item) for item in state.get("posting_request_ids", [])}
        self._posting_amount_by_request = {
            str(k): int(v) for k, v in dict(state.get("posting_amount_by_request", {})).items()
        }
        self._posting_account_by_request = {
            str(k): str(v) for k, v in dict(state.get("posting_account_by_request", {})).items()
        }
        self._reversed_original_ids = {str(item) for item in state.get("reversed_original_ids", [])}
        self._next_sequence_no = int(state.get("next_sequence_no", 1))

    def process(self, transactions: Iterable[Transaction], business_date: str) -> EngineResult:
        journal: list[JournalRecord] = []
        exceptions: list[ExceptionRecord] = []
        total_post_cents = 0
        total_reverse_cents = 0
        applied_records = 0
        for txn in transactions:
            sequence_no = self._next_sequence_no
            self._next_sequence_no += 1
            before = self._balances.get(txn.account_id, 0)
            after = before
            amount_effect = 0
            status = "UNKNOWN"
            audit_event = "UNKNOWN"

            if txn.business_date != business_date:
                status = "BUSINESS_DATE_MISMATCH"
                audit_event = "TXN_REJECTED"
                exceptions.append(
                    ExceptionRecord(
                        business_date=business_date,
                        account_id=txn.account_id,
                        request_id=txn.request_id,
                        error_code=status,
                        detail=f"expected={business_date} actual={txn.business_date}",
                    )
                )
            elif txn.operation == "POST":
                if txn.request_id in self._processed_request_ids:
                    status = "DUPLICATE_IGNORED"
                    audit_event = "POST_DUPLICATE"
                else:
                    amount_effect = txn.amount_cents
                    after = before + amount_effect
                    self._balances[txn.account_id] = after
                    self._processed_request_ids.add(txn.request_id)
                    self._posting_request_ids.add(txn.request_id)
                    self._posting_amount_by_request[txn.request_id] = txn.amount_cents
                    self._posting_account_by_request[txn.request_id] = txn.account_id
                    status = "APPLIED"
                    audit_event = "POST_APPLIED"
                    total_post_cents += txn.amount_cents
                    applied_records += 1

            elif txn.operation == "REVERSE":
                if txn.request_id in self._processed_request_ids:
                    status = "DUPLICATE_IGNORED"
                    audit_event = "REVERSE_DUPLICATE"
                elif txn.original_request_id not in self._posting_request_ids:
                    status = "ORIG_NOT_FOUND"
                    audit_event = "REVERSE_REJECTED"
                    self._processed_request_ids.add(txn.request_id)
                    exceptions.append(
                        ExceptionRecord(
                            business_date=business_date,
                            account_id=txn.account_id,
                            request_id=txn.request_id,
                            error_code=status,
                            detail=f"original_request_id={txn.original_request_id}",
                        )
                    )
                elif txn.original_request_id in self._reversed_original_ids:
                    status = "ORIG_ALREADY_REVERSED"
                    audit_event = "REVERSE_REJECTED"
                    self._processed_request_ids.add(txn.request_id)
                    exceptions.append(
                        ExceptionRecord(
                            business_date=business_date,
                            account_id=txn.account_id,
                            request_id=txn.request_id,
                            error_code=status,
                            detail=f"original_request_id={txn.original_request_id}",
                        )
                    )
                else:
                    original_account = self._posting_account_by_request[txn.original_request_id]
                    if original_account != txn.account_id:
                        status = "ACCOUNT_MISMATCH"
                        audit_event = "REVERSE_REJECTED"
                        self._processed_request_ids.add(txn.request_id)
                        exceptions.append(
                            ExceptionRecord(
                                business_date=business_date,
                                account_id=txn.account_id,
                                request_id=txn.request_id,
                                error_code=status,
                                detail=f"original_account={original_account}",
                            )
                        )
                    else:
                        reverse_amount = self._posting_amount_by_request[txn.original_request_id]
                        amount_effect = -reverse_amount
                        after = before + amount_effect
                        self._balances[txn.account_id] = after
                        self._processed_request_ids.add(txn.request_id)
                        self._reversed_original_ids.add(txn.original_request_id)
                        status = "APPLIED"
                        audit_event = "REVERSE_APPLIED"
                        total_reverse_cents += reverse_amount
                        applied_records += 1
            else:
                status = "BAD_OPERATION"
                audit_event = "TXN_REJECTED"
                exceptions.append(
                    ExceptionRecord(
                        business_date=business_date,
                        account_id=txn.account_id,
                        request_id=txn.request_id,
                        error_code=status,
                        detail=f"operation={txn.operation}",
                    )
                )

            journal.append(
                JournalRecord(
                    sequence_no=sequence_no,
                    business_date=business_date,
                    account_id=txn.account_id,
                    request_id=txn.request_id,
                    operation=txn.operation,
                    original_request_id=txn.original_request_id,
                    amount_cents=amount_effect,
                    balance_before_cents=before,
                    balance_after_cents=after,
                    status=status,
                    audit_event=audit_event,
                )
            )

        closing_total = sum(self._balances.values())
        totals = ReconcileTotals(
            business_date=business_date,
            total_post_cents=total_post_cents,
            total_reverse_cents=total_reverse_cents,
            net_delta_cents=total_post_cents - total_reverse_cents,
            closing_total_cents=closing_total,
            records_processed=len(journal),
            applied_records=applied_records,
            exception_count=len(exceptions),
        )
        return EngineResult(journal=journal, exceptions=exceptions, totals=totals)
