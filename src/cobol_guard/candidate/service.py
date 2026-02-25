from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


class PostRequest(BaseModel):
    request_id: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    amount_cents: int
    business_date: str
    event_time: str


class ReverseRequest(BaseModel):
    reverse_request_id: str = Field(min_length=1)
    original_request_id: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    business_date: str
    event_time: str


class TxnResponse(BaseModel):
    request_id: str
    status: str
    balance_before_cents: int
    balance_after_cents: int
    amount_effect_cents: int


class ReplayRequest(BaseModel):
    operations: list[dict]


class ReconcileResponse(BaseModel):
    run_id: str
    business_date: str
    total_post_cents: int
    total_reverse_cents: int
    net_delta_cents: int
    closing_total_cents: int
    exception_count: int


@dataclass(slots=True)
class CandidateLedgerState:
    balances: dict[str, int]
    processed: set[str]
    posts: dict[str, tuple[str, int]]
    reversed_originals: set[str]
    reconcile_reports: dict[str, dict]
    next_run_id: int


class CandidateLedger:
    def __init__(self) -> None:
        self._state = CandidateLedgerState(
            balances={},
            processed=set(),
            posts={},
            reversed_originals=set(),
            reconcile_reports={},
            next_run_id=1,
        )
        self._lock = RLock()

    def post(self, req: PostRequest) -> TxnResponse:
        with self._lock:
            before = self._state.balances.get(req.account_id, 0)
            if req.request_id in self._state.processed:
                return TxnResponse(
                    request_id=req.request_id,
                    status="DUPLICATE_IGNORED",
                    balance_before_cents=before,
                    balance_after_cents=before,
                    amount_effect_cents=0,
                )
            after = before + req.amount_cents
            self._state.balances[req.account_id] = after
            self._state.processed.add(req.request_id)
            self._state.posts[req.request_id] = (req.account_id, req.amount_cents)
            return TxnResponse(
                request_id=req.request_id,
                status="APPLIED",
                balance_before_cents=before,
                balance_after_cents=after,
                amount_effect_cents=req.amount_cents,
            )

    def reverse(self, req: ReverseRequest) -> TxnResponse:
        with self._lock:
            before = self._state.balances.get(req.account_id, 0)
            if req.reverse_request_id in self._state.processed:
                return TxnResponse(
                    request_id=req.reverse_request_id,
                    status="DUPLICATE_IGNORED",
                    balance_before_cents=before,
                    balance_after_cents=before,
                    amount_effect_cents=0,
                )
            original = self._state.posts.get(req.original_request_id)
            if original is None:
                self._state.processed.add(req.reverse_request_id)
                return TxnResponse(
                    request_id=req.reverse_request_id,
                    status="ORIG_NOT_FOUND",
                    balance_before_cents=before,
                    balance_after_cents=before,
                    amount_effect_cents=0,
                )
            original_account, original_amount = original
            if original_account != req.account_id:
                self._state.processed.add(req.reverse_request_id)
                return TxnResponse(
                    request_id=req.reverse_request_id,
                    status="ACCOUNT_MISMATCH",
                    balance_before_cents=before,
                    balance_after_cents=before,
                    amount_effect_cents=0,
                )
            if req.original_request_id in self._state.reversed_originals:
                self._state.processed.add(req.reverse_request_id)
                return TxnResponse(
                    request_id=req.reverse_request_id,
                    status="ORIG_ALREADY_REVERSED",
                    balance_before_cents=before,
                    balance_after_cents=before,
                    amount_effect_cents=0,
                )
            after = before - original_amount
            self._state.balances[req.account_id] = after
            self._state.processed.add(req.reverse_request_id)
            self._state.reversed_originals.add(req.original_request_id)
            return TxnResponse(
                request_id=req.reverse_request_id,
                status="APPLIED",
                balance_before_cents=before,
                balance_after_cents=after,
                amount_effect_cents=-original_amount,
            )

    def balance(self, account_id: str) -> int:
        with self._lock:
            return self._state.balances.get(account_id, 0)

    def replay(self, operations: list[dict]) -> list[TxnResponse]:
        results: list[TxnResponse] = []
        for item in operations:
            operation = str(item.get("operation", "")).upper()
            if operation == "POST":
                results.append(self.post(PostRequest(**item)))
            elif operation == "REVERSE":
                payload = dict(item)
                payload["reverse_request_id"] = payload.pop("request_id", payload.get("reverse_request_id"))
                results.append(self.reverse(ReverseRequest(**payload)))
            else:
                raise ValueError(f"Unsupported operation in replay: {operation}")
        return results

    def reconcile(self, business_date: str) -> dict:
        with self._lock:
            total_post_cents = sum(amount for (_, amount) in self._state.posts.values())
            total_reverse_cents = sum(
                self._state.posts[request_id][1] for request_id in self._state.reversed_originals if request_id in self._state.posts
            )
            net_delta = total_post_cents - total_reverse_cents
            closing_total = sum(self._state.balances.values())
            run_id = f"recon-{self._state.next_run_id:06d}"
            self._state.next_run_id += 1
            report = {
                "run_id": run_id,
                "business_date": business_date,
                "total_post_cents": total_post_cents,
                "total_reverse_cents": total_reverse_cents,
                "net_delta_cents": net_delta,
                "closing_total_cents": closing_total,
                "exception_count": 0,
            }
            self._state.reconcile_reports[run_id] = report
            return report

    def get_reconcile_report(self, run_id: str) -> dict | None:
        with self._lock:
            return self._state.reconcile_reports.get(run_id)


app = FastAPI(title="COBOL Guard v2 Candidate Service", version="0.1.0")
ledger = CandidateLedger()


@app.post("/transactions/post", response_model=TxnResponse)
def post_transaction(request: PostRequest) -> TxnResponse:
    return ledger.post(request)


@app.post("/transactions/reverse", response_model=TxnResponse)
def reverse_transaction(request: ReverseRequest) -> TxnResponse:
    return ledger.reverse(request)


@app.get("/accounts/{account_id}/balance")
def get_balance(account_id: str) -> dict[str, int]:
    return {"account_id": account_id, "balance_cents": ledger.balance(account_id=account_id)}


@app.post("/replay/execute")
def replay_execute(request: ReplayRequest) -> dict[str, list[dict]]:
    try:
        results = [item.model_dump() for item in ledger.replay(request.operations)]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"results": results}


@app.post("/batch/reconcile/run", response_model=ReconcileResponse)
def run_reconcile(payload: dict[str, str]) -> ReconcileResponse:
    business_date = payload.get("business_date")
    if not business_date:
        raise HTTPException(status_code=400, detail="business_date is required")
    report = ledger.reconcile(business_date=business_date)
    return ReconcileResponse(**report)


@app.get("/batch/reconcile/{run_id}/report", response_model=ReconcileResponse)
def get_reconcile(run_id: str) -> ReconcileResponse:
    report = ledger.get_reconcile_report(run_id=run_id)
    if report is None:
        raise HTTPException(status_code=404, detail=f"run_id not found: {run_id}")
    return ReconcileResponse(**report)


def main() -> None:
    uvicorn.run("cobol_guard.candidate.service:app", host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    main()
