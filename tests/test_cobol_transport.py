from cobol_guard.contracts import Transaction
from cobol_guard.oracle.cobol_transport import (
    TXN_RECORD_LENGTH,
    fixed_width_to_transaction,
    transaction_to_fixed_width,
)


def test_cobol_transport_round_trip() -> None:
    txn = Transaction(
        request_id="REQ000000000001",
        operation="POST",
        original_request_id="",
        account_id="ACC000000001",
        amount_cents=12345,
        business_date="20260110",
        event_time="20260110120000",
    )
    line = transaction_to_fixed_width(txn)
    assert len(line) == TXN_RECORD_LENGTH
    decoded = fixed_width_to_transaction(line)
    assert decoded.request_id == txn.request_id
    assert decoded.operation == "POST"
    assert decoded.amount_cents == 12345
