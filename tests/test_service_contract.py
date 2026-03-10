from pathlib import Path

from cobol_guard.candidate.service import CandidateLedger, PostRequest, ReverseRequest


def test_reverse_contract_idempotency(tmp_path: Path) -> None:
    ledger = CandidateLedger(database_url=f"sqlite+pysqlite:///{tmp_path / 'ledger.db'}")
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
    assert duplicate_reverse.status == "APPLIED"
    assert duplicate_reverse.amount_effect_cents == -1000

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


def test_replay_rolls_back_entire_batch(tmp_path: Path) -> None:
    ledger = CandidateLedger(database_url=f"sqlite+pysqlite:///{tmp_path / 'ledger.db'}")

    try:
        ledger.replay(
            [
                {
                    "operation": "POST",
                    "request_id": "REQ1",
                    "account_id": "ACC000000001",
                    "amount_cents": 1000,
                    "business_date": "20260110",
                    "event_time": "20260110120000",
                },
                {
                    "operation": "UNKNOWN",
                    "request_id": "REQ2",
                    "account_id": "ACC000000001",
                    "amount_cents": 1000,
                    "business_date": "20260110",
                    "event_time": "20260110120100",
                },
            ]
        )
    except ValueError as exc:
        assert "Unsupported operation" in str(exc)
    else:
        raise AssertionError("expected replay to fail")

    assert ledger.balance("ACC000000001") == 0


def test_ledger_persists_across_instances(tmp_path: Path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'ledger.db'}"
    first = CandidateLedger(database_url=database_url)
    first.post(
        PostRequest(
            request_id="REQ1",
            account_id="ACC000000001",
            amount_cents=2200,
            business_date="20260110",
            event_time="20260110120000",
        )
    )

    second = CandidateLedger(database_url=database_url)
    assert second.balance("ACC000000001") == 2200
