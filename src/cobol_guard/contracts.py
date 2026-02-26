from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


def _fit_text(value: Any, width: int) -> str:
    return str(value)[:width]


@dataclass(slots=True)
class Transaction:
    request_id: str
    operation: str
    original_request_id: str
    account_id: str
    amount_cents: int
    business_date: str
    event_time: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Transaction":
        return cls(
            request_id=_fit_text(payload["request_id"], 16),
            operation=_fit_text(str(payload["operation"]).upper(), 8),
            original_request_id=_fit_text(payload.get("original_request_id", ""), 16),
            account_id=_fit_text(payload["account_id"], 12),
            amount_cents=int(payload.get("amount_cents", 0)),
            business_date=_fit_text(payload["business_date"], 8),
            event_time=_fit_text(payload["event_time"], 14),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class JournalRecord:
    sequence_no: int
    business_date: str
    account_id: str
    request_id: str
    operation: str
    original_request_id: str
    amount_cents: int
    balance_before_cents: int
    balance_after_cents: int
    status: str
    audit_event: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ExceptionRecord:
    business_date: str
    account_id: str
    request_id: str
    error_code: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ReconcileTotals:
    business_date: str
    total_post_cents: int
    total_reverse_cents: int
    net_delta_cents: int
    closing_total_cents: int
    records_processed: int
    applied_records: int
    exception_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
