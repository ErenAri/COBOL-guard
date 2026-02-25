from cobol_guard.candidate.service import CandidateLedger, PostRequest, ReverseRequest


def test_reverse_contract_idempotency() -> None:
    ledger = CandidateLedger()
    post = ledger.post(
        PostRequest(
            request_id="REQ1",
            account_id="ACC000000001",
            amount_cents=1000,
            business_date="20260110",
            event_time="20260110120000",
        )
    )
    assert post.status == "APPLIED"

    first_reverse = ledger.reverse(
        ReverseRequest(
            reverse_request_id="REV1",
            original_request_id="REQ1",
            account_id="ACC000000001",
            business_date="20260110",
            event_time="20260110120100",
        )
    )
    assert first_reverse.status == "APPLIED"

    duplicate_reverse = ledger.reverse(
        ReverseRequest(
            reverse_request_id="REV1",
            original_request_id="REQ1",
            account_id="ACC000000001",
            business_date="20260110",
            event_time="20260110120200",
        )
    )
    assert duplicate_reverse.status == "DUPLICATE_IGNORED"
    assert duplicate_reverse.amount_effect_cents == 0

    different_reverse_id = ledger.reverse(
        ReverseRequest(
            reverse_request_id="REV2",
            original_request_id="REQ1",
            account_id="ACC000000001",
            business_date="20260110",
            event_time="20260110120300",
        )
    )
    assert different_reverse_id.status == "ORIG_ALREADY_REVERSED"
