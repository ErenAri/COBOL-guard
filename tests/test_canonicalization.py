from cobol_guard.schema_registry import (
    canonical_record_text,
    canonical_sort_key,
    load_schema,
    parse_record_text,
)


def test_canonical_record_bytes_are_deterministic() -> None:
    schema = load_schema("ledger_journal", version_hint="1")
    record = {
        "sequence_no": 1,
        "business_date": "20260110",
        "account_id": "ACC000000001",
        "request_id": "REQ000000000001",
        "operation": "POST",
        "original_request_id": "",
        "amount_cents": 15000,
        "balance_before_cents": 0,
        "balance_after_cents": 15000,
        "status": "APPLIED",
        "audit_event": "POST_APPLIED",
    }
    first = canonical_record_text(record=record, schema=schema)
    second = canonical_record_text(record=record, schema=schema)
    assert first == second


def test_sort_key_uses_fingerprint_as_final_tiebreaker() -> None:
    schema = load_schema("exception_report", version_hint="1")
    left = {
        "business_date": "20260110",
        "account_id": "ACC000000001",
        "request_id": "REQ000000000005",
        "error_code": "ORIG_NOT_FOUND",
        "detail": "A",
    }
    right = {
        "business_date": "20260110",
        "account_id": "ACC000000001",
        "request_id": "REQ000000000005",
        "error_code": "ORIG_NOT_FOUND",
        "detail": "B",
    }
    assert canonical_sort_key(left, schema) != canonical_sort_key(right, schema)


def test_round_trip_parse_canonical_text() -> None:
    schema = load_schema("ledger_journal", version_hint="1")
    record = {
        "sequence_no": 42,
        "business_date": "20260110",
        "account_id": "ACC000000777",
        "request_id": "REQ000000000777",
        "operation": "POST",
        "original_request_id": "",
        "amount_cents": 12345,
        "balance_before_cents": 0,
        "balance_after_cents": 12345,
        "status": "APPLIED",
        "audit_event": "POST_APPLIED",
    }
    line = canonical_record_text(record=record, schema=schema)
    parsed = parse_record_text(line=line, schema=schema)
    assert parsed["sequence_no"] == 42
    assert parsed["request_id"] == "REQ000000000777"
    assert parsed["amount_cents"] == 12345
