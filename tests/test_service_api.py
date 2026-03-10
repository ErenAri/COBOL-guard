from pathlib import Path

import jwt
from fastapi.testclient import TestClient

from cobol_guard.candidate.service import ServiceSettings, build_app


def _build_client(
    tmp_path: Path,
    *,
    auth_mode: str = "disabled",
    secret: str = "test-secret",
    read_rps: int = 50,
    write_rps: int = 10,
) -> TestClient:
    settings = ServiceSettings(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'service.db'}",
        auth_mode=auth_mode,
        hs256_secret=secret if auth_mode == "hs256" else "",
        jwt_issuer="cobol-guard-tests" if auth_mode == "hs256" else "",
        jwt_audience="cobol-guard-api" if auth_mode == "hs256" else "",
        write_rps=write_rps,
        read_rps=read_rps,
    )
    return TestClient(build_app(settings=settings))


def _auth_headers(*, secret: str = "test-secret", scopes: str = "ledger.read ledger.write ops.metrics") -> dict[str, str]:
    token = jwt.encode(
        {
            "sub": "svc-test",
            "scope": scopes,
            "iss": "cobol-guard-tests",
            "aud": "cobol-guard-api",
        },
        secret,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def test_transaction_routes_share_engine_behavior(tmp_path: Path) -> None:
    client = _build_client(tmp_path)

    post_payload = {
        "request_id": "REQ1",
        "account_id": "ACC000000001",
        "amount_cents": 1000,
        "business_date": "20260110",
        "event_time": "20260110120000",
    }
    first_post = client.post("/transactions/post", json=post_payload)
    duplicate_post = client.post("/transactions/post", json=post_payload)
    reverse = client.post(
        "/transactions/reverse",
        json={
            "reverse_request_id": "REV1",
            "original_request_id": "REQ1",
            "account_id": "ACC000000001",
            "business_date": "20260110",
            "event_time": "20260110120100",
        },
    )
    balance = client.get("/accounts/ACC000000001/balance")

    assert first_post.status_code == 200
    assert first_post.json()["status"] == "APPLIED"
    assert duplicate_post.status_code == 200
    assert duplicate_post.json()["status"] == "APPLIED"
    assert reverse.status_code == 200
    assert reverse.json()["status"] == "APPLIED"
    assert balance.status_code == 200
    assert balance.json() == {"account_id": "ACC000000001", "balance_cents": 0}


def test_replay_execute_returns_400_for_invalid_operation_and_rolls_back(tmp_path: Path) -> None:
    client = _build_client(tmp_path)

    response = client.post(
        "/replay/execute",
        json={
            "operations": [
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
                    "event_time": "20260110120001",
                },
            ]
        },
    )

    balance = client.get("/accounts/ACC000000001/balance")
    assert response.status_code == 400
    assert response.json()["code"] == "replay_invalid"
    assert balance.json()["balance_cents"] == 0


def test_reconcile_routes_report_cumulative_totals_and_missing_report(tmp_path: Path) -> None:
    client = _build_client(tmp_path)
    client.post(
        "/transactions/reverse",
        json={
            "reverse_request_id": "REV_MISSING",
            "original_request_id": "REQ_MISSING",
            "account_id": "ACC000000001",
            "business_date": "20260110",
            "event_time": "20260110115900",
        },
    )
    client.post(
        "/transactions/post",
        json={
            "request_id": "REQ1",
            "account_id": "ACC000000001",
            "amount_cents": 2500,
            "business_date": "20260110",
            "event_time": "20260110120000",
        },
    )
    client.post(
        "/transactions/reverse",
        json={
            "reverse_request_id": "REV1",
            "original_request_id": "REQ1",
            "account_id": "ACC000000001",
            "business_date": "20260110",
            "event_time": "20260110120100",
        },
    )

    reconcile = client.post("/batch/reconcile/run", json={"business_date": "20260110"})
    missing = client.get("/batch/reconcile/does-not-exist/report")

    assert reconcile.status_code == 200
    assert reconcile.json()["total_post_cents"] == 2500
    assert reconcile.json()["total_reverse_cents"] == 2500
    assert reconcile.json()["closing_total_cents"] == 0
    assert reconcile.json()["exception_count"] == 1
    assert missing.status_code == 404


def test_health_readiness_and_metrics_routes(tmp_path: Path) -> None:
    client = _build_client(tmp_path, auth_mode="hs256")

    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").json() == {"status": "ready"}

    metrics = client.get("/metrics", headers=_auth_headers(scopes="ops.metrics"))
    assert metrics.status_code == 200
    assert "cobol_guard_http_requests_total" in metrics.text


def test_authentication_and_scope_failures_are_enforced(tmp_path: Path) -> None:
    client = _build_client(tmp_path, auth_mode="hs256")

    missing_token = client.get("/accounts/ACC000000001/balance")
    wrong_scope = client.post(
        "/transactions/post",
        json={
            "request_id": "REQ1",
            "account_id": "ACC000000001",
            "amount_cents": 100,
            "business_date": "20260110",
            "event_time": "20260110120000",
        },
        headers=_auth_headers(scopes="ledger.read"),
    )

    assert missing_token.status_code == 401
    assert missing_token.json()["code"] == "missing_token"
    assert wrong_scope.status_code == 403
    assert wrong_scope.json()["code"] == "insufficient_scope"


def test_rate_limit_hits_return_429(tmp_path: Path) -> None:
    client = _build_client(tmp_path, auth_mode="hs256", read_rps=1)
    headers = _auth_headers(scopes="ledger.read")

    first = client.get("/accounts/ACC000000001/balance", headers=headers)
    second = client.get("/accounts/ACC000000001/balance", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["code"] == "rate_limited"
