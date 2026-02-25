from pathlib import Path

from cobol_guard.candidate.engine import LedgerEngine
from cobol_guard.contracts import Transaction
from cobol_guard.io_utils import read_jsonl


def test_reverse_is_idempotent_and_totals_consistent() -> None:
    fixture_path = Path("fixtures/inputs/basic_transactions.jsonl")
    transactions = [Transaction.from_dict(item) for item in read_jsonl(fixture_path)]
    result = LedgerEngine().process(transactions=transactions, business_date="20260110")

    statuses = [record.status for record in result.journal]
    assert "DUPLICATE_IGNORED" in statuses
    assert any(item.error_code == "ORIG_NOT_FOUND" for item in result.exceptions)
    assert result.totals.total_post_cents == 21200
    assert result.totals.total_reverse_cents == 5000
    assert result.totals.net_delta_cents == 16200
    assert result.totals.closing_total_cents == 16200
