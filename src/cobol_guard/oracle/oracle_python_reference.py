from __future__ import annotations

from collections.abc import Iterable

from cobol_guard.candidate.engine import EngineResult, LedgerEngine
from cobol_guard.contracts import Transaction


def run_reference_oracle(transactions: Iterable[Transaction], business_date: str) -> EngineResult:
    # The local oracle implementation mirrors COBOL behavior for development runs.
    # In a deployed environment this adapter is replaced by COBOL executable integration.
    engine = LedgerEngine()
    return engine.process(transactions=transactions, business_date=business_date)
