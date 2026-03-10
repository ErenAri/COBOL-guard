from __future__ import annotations

import json
import logging
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import Lock
from uuid import uuid4

import jwt
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, Counter, Histogram, generate_latest
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import Column, Engine, Integer, MetaData, String, Table, create_engine, select, text
from sqlalchemy.pool import StaticPool

from cobol_guard.candidate.engine import LedgerEngine
from cobol_guard.contracts import Transaction

DEFAULT_DATABASE_URL = "sqlite+pysqlite:///./cobol_guard.service.db"
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_WRITE_RPS = 10
DEFAULT_READ_RPS = 50

def _metric(factory, name: str, documentation: str, labels: list[str]):
    existing = REGISTRY._names_to_collectors.get(name) or REGISTRY._names_to_collectors.get(f"{name}_total")
    if existing is not None:
        return existing
    return factory(name, documentation, labels)


REQUEST_COUNTER = _metric(
    Counter,
    "cobol_guard_http_requests",
    "HTTP requests handled by the candidate service",
    ["method", "route", "status_code"],
)
REQUEST_LATENCY = _metric(
    Histogram,
    "cobol_guard_http_request_latency_seconds",
    "HTTP request latency for the candidate service",
    ["method", "route"],
)
AUTH_FAILURE_COUNTER = _metric(
    Counter,
    "cobol_guard_auth_failures",
    "Authentication failures",
    ["reason"],
)
RATE_LIMIT_COUNTER = _metric(
    Counter,
    "cobol_guard_rate_limit_hits",
    "Rate-limit rejections",
    ["bucket"],
)
DUPLICATE_COUNTER = _metric(
    Counter,
    "cobol_guard_duplicate_requests",
    "Duplicate request ids returned from persistent storage",
    ["operation"],
)
RECONCILE_COUNTER = _metric(
    Counter,
    "cobol_guard_reconcile_runs",
    "Reconcile runs persisted by the service",
    [],
)

metadata = MetaData()
ledger_requests = Table(
    "ledger_requests",
    metadata,
    Column("request_id", String(32), primary_key=True),
    Column("sequence_no", Integer, nullable=False),
    Column("operation", String(8), nullable=False),
    Column("original_request_id", String(32), nullable=False, default=""),
    Column("account_id", String(32), nullable=False),
    Column("amount_cents", Integer, nullable=False),
    Column("business_date", String(8), nullable=False),
    Column("event_time", String(14), nullable=False),
    Column("status", String(32), nullable=False),
    Column("audit_event", String(32), nullable=False),
    Column("amount_effect_cents", Integer, nullable=False),
    Column("balance_before_cents", Integer, nullable=False),
    Column("balance_after_cents", Integer, nullable=False),
    Column("exception_detail", String(255), nullable=False, default=""),
    Column("created_at_utc", String(32), nullable=False),
)
account_balances = Table(
    "account_balances",
    metadata,
    Column("account_id", String(32), primary_key=True),
    Column("balance_cents", Integer, nullable=False),
    Column("updated_at_utc", String(32), nullable=False),
)
reconcile_runs = Table(
    "reconcile_runs",
    metadata,
    Column("run_id", String(32), primary_key=True),
    Column("business_date", String(8), nullable=False),
    Column("total_post_cents", Integer, nullable=False),
    Column("total_reverse_cents", Integer, nullable=False),
    Column("net_delta_cents", Integer, nullable=False),
    Column("closing_total_cents", Integer, nullable=False),
    Column("exception_count", Integer, nullable=False),
    Column("created_at_utc", String(32), nullable=False),
)

EXCEPTION_STATUSES = {
    "BUSINESS_DATE_MISMATCH",
    "ORIG_NOT_FOUND",
    "ORIG_ALREADY_REVERSED",
    "ACCOUNT_MISMATCH",
    "BAD_OPERATION",
}


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _scope_set(payload: dict) -> set[str]:
    raw = payload.get("scope", payload.get("scp", ""))
    if isinstance(raw, str):
        return {item.strip() for item in raw.split() if item.strip()}
    if isinstance(raw, list):
        return {str(item).strip() for item in raw if str(item).strip()}
    return set()


def _sqlite_connect_args(database_url: str) -> dict:
    if not database_url.startswith("sqlite"):
        return {}
    return {"check_same_thread": False}


def _create_engine(database_url: str) -> Engine:
    kwargs: dict = {"future": True, "connect_args": _sqlite_connect_args(database_url)}
    if database_url.endswith(":memory:"):
        kwargs["poolclass"] = StaticPool
    return create_engine(database_url, **kwargs)


def _normalize_db_url(database_url: str | None) -> str:
    return str(database_url or DEFAULT_DATABASE_URL)


def _database_url_from_env() -> str:
    return _normalize_db_url(os.environ.get("COBOL_GUARD_DATABASE_URL"))


def _log_level_from_env() -> str:
    return os.environ.get("COBOL_GUARD_LOG_LEVEL", DEFAULT_LOG_LEVEL).upper()


def _auth_mode_from_env() -> str:
    return os.environ.get("COBOL_GUARD_AUTH_MODE", "disabled").strip().lower() or "disabled"


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return int(raw)


def _security_bearer() -> HTTPBearer:
    return HTTPBearer(auto_error=False)


def _account_id(value: str) -> str:
    return value[:12]


class ServiceError(Exception):
    def __init__(self, *, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class PostRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=16)
    account_id: str = Field(min_length=1, max_length=12)
    amount_cents: int
    business_date: str
    event_time: str

    @field_validator("business_date")
    @classmethod
    def validate_business_date(cls, value: str) -> str:
        if len(value) != 8 or not value.isdigit():
            raise ValueError("business_date must be YYYYMMDD")
        return value

    @field_validator("event_time")
    @classmethod
    def validate_event_time(cls, value: str) -> str:
        if len(value) != 14 or not value.isdigit():
            raise ValueError("event_time must be YYYYMMDDHHMMSS")
        return value


class ReverseRequest(BaseModel):
    reverse_request_id: str = Field(min_length=1, max_length=16)
    original_request_id: str = Field(min_length=1, max_length=16)
    account_id: str = Field(min_length=1, max_length=12)
    business_date: str
    event_time: str

    @field_validator("business_date")
    @classmethod
    def validate_business_date(cls, value: str) -> str:
        if len(value) != 8 or not value.isdigit():
            raise ValueError("business_date must be YYYYMMDD")
        return value

    @field_validator("event_time")
    @classmethod
    def validate_event_time(cls, value: str) -> str:
        if len(value) != 14 or not value.isdigit():
            raise ValueError("event_time must be YYYYMMDDHHMMSS")
        return value


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


class BalanceResponse(BaseModel):
    account_id: str
    balance_cents: int


class ErrorResponse(BaseModel):
    code: str
    message: str
    request_id: str


@dataclass(slots=True)
class Principal:
    subject: str
    scopes: set[str]


@dataclass(slots=True)
class ServiceSettings:
    database_url: str = field(default_factory=_database_url_from_env)
    log_level: str = field(default_factory=_log_level_from_env)
    auth_mode: str = field(default_factory=_auth_mode_from_env)
    jwt_issuer: str = field(default_factory=lambda: os.environ.get("COBOL_GUARD_JWT_ISSUER", "").strip())
    jwt_audience: str = field(default_factory=lambda: os.environ.get("COBOL_GUARD_JWT_AUDIENCE", "").strip())
    jwks_url: str = field(default_factory=lambda: os.environ.get("COBOL_GUARD_JWKS_URL", "").strip())
    hs256_secret: str = field(default_factory=lambda: os.environ.get("COBOL_GUARD_JWT_HS256_SECRET", "").strip())
    write_rps: int = field(default_factory=lambda: _int_env("COBOL_GUARD_RATE_LIMIT_WRITE_RPS", DEFAULT_WRITE_RPS))
    read_rps: int = field(default_factory=lambda: _int_env("COBOL_GUARD_RATE_LIMIT_READ_RPS", DEFAULT_READ_RPS))


class FixedWindowRateLimiter:
    def __init__(self) -> None:
        self._lock = Lock()
        self._buckets: dict[tuple[str, int], tuple[int, float]] = {}

    def allow(self, *, key: str, limit: int) -> bool:
        if limit <= 0:
            return True
        now = time.monotonic()
        window = int(now)
        bucket_key = (key, window)
        with self._lock:
            count, expires_at = self._buckets.get(bucket_key, (0, float(window + 1)))
            if now >= expires_at:
                count = 0
                expires_at = float(window + 1)
            if count >= limit:
                return False
            self._buckets[bucket_key] = (count + 1, expires_at)
        return True


class CandidateLedger:
    def __init__(self, *, database_url: str | None = None) -> None:
        self.database_url = _normalize_db_url(database_url)
        self.engine = _create_engine(self.database_url)
        self._last_ready_error = ""
        self.ensure_schema()

    @property
    def last_ready_error(self) -> str:
        return self._last_ready_error

    def ensure_schema(self) -> None:
        try:
            metadata.create_all(self.engine)
            self._last_ready_error = ""
        except Exception as exc:
            self._last_ready_error = str(exc)
            raise

    def is_ready(self) -> bool:
        try:
            self.ensure_schema()
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            self._last_ready_error = ""
            return True
        except Exception as exc:
            self._last_ready_error = str(exc)
            return False

    def _existing_response(self, conn, request_id: str) -> TxnResponse | None:
        row = conn.execute(
            select(
                ledger_requests.c.request_id,
                ledger_requests.c.status,
                ledger_requests.c.balance_before_cents,
                ledger_requests.c.balance_after_cents,
                ledger_requests.c.amount_effect_cents,
            ).where(ledger_requests.c.request_id == request_id)
        ).mappings().first()
        if row is None:
            return None
        DUPLICATE_COUNTER.labels(operation="lookup").inc()
        return TxnResponse(
            request_id=str(row["request_id"]),
            status=str(row["status"]),
            balance_before_cents=int(row["balance_before_cents"]),
            balance_after_cents=int(row["balance_after_cents"]),
            amount_effect_cents=int(row["amount_effect_cents"]),
        )

    def _load_engine_state(self, conn) -> tuple[dict, int]:
        request_rows = conn.execute(
            select(
                ledger_requests.c.request_id,
                ledger_requests.c.sequence_no,
                ledger_requests.c.operation,
                ledger_requests.c.original_request_id,
                ledger_requests.c.account_id,
                ledger_requests.c.amount_cents,
                ledger_requests.c.status,
            ).order_by(ledger_requests.c.sequence_no.asc())
        ).mappings().all()
        balance_rows = conn.execute(
            select(account_balances.c.account_id, account_balances.c.balance_cents)
        ).mappings().all()

        next_sequence_no = 1
        processed_request_ids: list[str] = []
        posting_request_ids: list[str] = []
        posting_amount_by_request: dict[str, int] = {}
        posting_account_by_request: dict[str, str] = {}
        reversed_original_ids: list[str] = []

        for row in request_rows:
            request_id = str(row["request_id"])
            processed_request_ids.append(request_id)
            next_sequence_no = max(next_sequence_no, int(row["sequence_no"]) + 1)
            if row["operation"] == "POST" and row["status"] == "APPLIED":
                posting_request_ids.append(request_id)
                posting_amount_by_request[request_id] = int(row["amount_cents"])
                posting_account_by_request[request_id] = str(row["account_id"])
            if row["operation"] == "REVERSE" and row["status"] == "APPLIED":
                original = str(row["original_request_id"])
                if original:
                    reversed_original_ids.append(original)

        state = {
            "balances": {str(row["account_id"]): int(row["balance_cents"]) for row in balance_rows},
            "processed_request_ids": processed_request_ids,
            "posting_request_ids": posting_request_ids,
            "posting_amount_by_request": posting_amount_by_request,
            "posting_account_by_request": posting_account_by_request,
            "reversed_original_ids": reversed_original_ids,
            "next_sequence_no": next_sequence_no,
        }
        return state, next_sequence_no

    def _persist_balance(self, conn, *, account_id: str, balance_cents: int) -> None:
        exists = conn.execute(
            select(account_balances.c.account_id).where(account_balances.c.account_id == account_id)
        ).first()
        payload = {
            "account_id": account_id,
            "balance_cents": balance_cents,
            "updated_at_utc": _utc_now(),
        }
        if exists is None:
            conn.execute(account_balances.insert().values(**payload))
        else:
            conn.execute(
                account_balances.update().where(account_balances.c.account_id == account_id).values(**payload)
            )

    def _persist_transaction(self, conn, *, txn: Transaction, response: TxnResponse, audit_event: str, detail: str) -> None:
        sequence_no = int(
            conn.execute(select(ledger_requests.c.sequence_no).order_by(ledger_requests.c.sequence_no.desc())).scalar()
            or 0
        ) + 1
        conn.execute(
            ledger_requests.insert().values(
                request_id=txn.request_id,
                sequence_no=sequence_no,
                operation=txn.operation,
                original_request_id=txn.original_request_id,
                account_id=txn.account_id,
                amount_cents=txn.amount_cents,
                business_date=txn.business_date,
                event_time=txn.event_time,
                status=response.status,
                audit_event=audit_event,
                amount_effect_cents=response.amount_effect_cents,
                balance_before_cents=response.balance_before_cents,
                balance_after_cents=response.balance_after_cents,
                exception_detail=detail,
                created_at_utc=_utc_now(),
            )
        )
        if response.status == "APPLIED":
            self._persist_balance(
                conn,
                account_id=txn.account_id,
                balance_cents=response.balance_after_cents,
            )

    def _apply_transaction(self, conn, txn: Transaction) -> TxnResponse:
        existing = self._existing_response(conn, txn.request_id)
        if existing is not None:
            return existing

        state, _ = self._load_engine_state(conn)
        engine = LedgerEngine()
        engine.load_state(state)
        result = engine.process([txn], business_date=txn.business_date)
        journal = result.journal[0]
        detail = result.exceptions[0].detail if result.exceptions else ""
        response = TxnResponse(
            request_id=journal.request_id,
            status=journal.status,
            balance_before_cents=journal.balance_before_cents,
            balance_after_cents=journal.balance_after_cents,
            amount_effect_cents=journal.amount_cents,
        )
        self._persist_transaction(
            conn,
            txn=txn,
            response=response,
            audit_event=journal.audit_event,
            detail=detail,
        )
        return response

    def post(self, req: PostRequest) -> TxnResponse:
        txn = Transaction(
            request_id=req.request_id,
            operation="POST",
            original_request_id="",
            account_id=_account_id(req.account_id),
            amount_cents=req.amount_cents,
            business_date=req.business_date,
            event_time=req.event_time,
        )
        with self.engine.begin() as conn:
            return self._apply_transaction(conn, txn)

    def reverse(self, req: ReverseRequest) -> TxnResponse:
        txn = Transaction(
            request_id=req.reverse_request_id,
            operation="REVERSE",
            original_request_id=req.original_request_id,
            account_id=_account_id(req.account_id),
            amount_cents=0,
            business_date=req.business_date,
            event_time=req.event_time,
        )
        with self.engine.begin() as conn:
            return self._apply_transaction(conn, txn)

    def balance(self, account_id: str) -> int:
        with self.engine.begin() as conn:
            value = conn.execute(
                select(account_balances.c.balance_cents).where(account_balances.c.account_id == _account_id(account_id))
            ).scalar()
            return int(value or 0)

    def replay(self, operations: list[dict]) -> list[TxnResponse]:
        validated: list[Transaction] = []
        for item in operations:
            operation = str(item.get("operation", "")).upper()
            if operation == "POST":
                payload = PostRequest(**item)
                validated.append(
                    Transaction(
                        request_id=payload.request_id,
                        operation="POST",
                        original_request_id="",
                        account_id=_account_id(payload.account_id),
                        amount_cents=payload.amount_cents,
                        business_date=payload.business_date,
                        event_time=payload.event_time,
                    )
                )
            elif operation == "REVERSE":
                payload = dict(item)
                payload["reverse_request_id"] = payload.pop("request_id", payload.get("reverse_request_id"))
                parsed = ReverseRequest(**payload)
                validated.append(
                    Transaction(
                        request_id=parsed.reverse_request_id,
                        operation="REVERSE",
                        original_request_id=parsed.original_request_id,
                        account_id=_account_id(parsed.account_id),
                        amount_cents=0,
                        business_date=parsed.business_date,
                        event_time=parsed.event_time,
                    )
                )
            else:
                raise ValueError(f"Unsupported operation in replay: {operation}")

        results: list[TxnResponse] = []
        with self.engine.begin() as conn:
            for txn in validated:
                results.append(self._apply_transaction(conn, txn))
        return results

    def reconcile(self, business_date: str) -> dict:
        with self.engine.begin() as conn:
            request_rows = conn.execute(
                select(
                    ledger_requests.c.operation,
                    ledger_requests.c.amount_cents,
                    ledger_requests.c.amount_effect_cents,
                    ledger_requests.c.status,
                ).where(ledger_requests.c.business_date == business_date)
            ).mappings().all()
            balance_rows = conn.execute(select(account_balances.c.balance_cents)).all()
            existing_runs = conn.execute(select(reconcile_runs.c.run_id)).all()

            total_post_cents = sum(
                int(row["amount_cents"])
                for row in request_rows
                if row["operation"] == "POST" and row["status"] == "APPLIED"
            )
            total_reverse_cents = sum(
                abs(int(row["amount_effect_cents"]))
                for row in request_rows
                if row["operation"] == "REVERSE" and row["status"] == "APPLIED"
            )
            exception_count = sum(1 for row in request_rows if str(row["status"]) in EXCEPTION_STATUSES)
            closing_total_cents = sum(int(row[0]) for row in balance_rows)
            run_id = f"recon-{len(existing_runs) + 1:06d}"
            report = {
                "run_id": run_id,
                "business_date": business_date,
                "total_post_cents": total_post_cents,
                "total_reverse_cents": total_reverse_cents,
                "net_delta_cents": total_post_cents - total_reverse_cents,
                "closing_total_cents": closing_total_cents,
                "exception_count": exception_count,
            }
            conn.execute(
                reconcile_runs.insert().values(
                    **report,
                    created_at_utc=_utc_now(),
                )
            )
            RECONCILE_COUNTER.inc()
            return report

    def get_reconcile_report(self, run_id: str) -> dict | None:
        with self.engine.begin() as conn:
            row = conn.execute(select(reconcile_runs).where(reconcile_runs.c.run_id == run_id)).mappings().first()
            if row is None:
                return None
            return {
                "run_id": str(row["run_id"]),
                "business_date": str(row["business_date"]),
                "total_post_cents": int(row["total_post_cents"]),
                "total_reverse_cents": int(row["total_reverse_cents"]),
                "net_delta_cents": int(row["net_delta_cents"]),
                "closing_total_cents": int(row["closing_total_cents"]),
                "exception_count": int(row["exception_count"]),
            }


def _configure_logging(level: str) -> logging.Logger:
    logger = logging.getLogger("cobol_guard.candidate.service")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    return logger


def _decode_jwt(token: str, settings: ServiceSettings) -> dict:
    issuer = settings.jwt_issuer or None
    audience = settings.jwt_audience or None
    if settings.auth_mode == "jwks":
        if not settings.jwks_url:
            raise ServiceError(status_code=500, code="auth_misconfigured", message="jwks_url is required")
        signing_key = jwt.PyJWKClient(settings.jwks_url).get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"],
            issuer=issuer,
            audience=audience,
        )
    if settings.auth_mode == "hs256":
        if not settings.hs256_secret:
            raise ServiceError(status_code=500, code="auth_misconfigured", message="hs256 secret is required")
        return jwt.decode(
            token,
            settings.hs256_secret,
            algorithms=["HS256"],
            issuer=issuer,
            audience=audience,
        )
    raise ServiceError(status_code=500, code="auth_misconfigured", message=f"unsupported auth_mode: {settings.auth_mode}")


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "")) or uuid4().hex


def build_app(*, settings: ServiceSettings | None = None, ledger: CandidateLedger | None = None) -> FastAPI:
    settings = settings or ServiceSettings()
    ledger = ledger or CandidateLedger(database_url=settings.database_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        ledger.ensure_schema()
        yield

    app = FastAPI(title="COBOL Guard v2 Candidate Service", version="0.2.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.ledger = ledger
    app.state.logger = _configure_logging(settings.log_level)
    app.state.rate_limiter = FixedWindowRateLimiter()
    security = _security_bearer()

    def service_error_response(request: Request, *, status_code: int, code: str, message: str) -> JSONResponse:
        return JSONResponse(
            status_code=status_code,
            content=ErrorResponse(code=code, message=message, request_id=_request_id(request)).model_dump(),
        )

    def get_principal(
        request: Request,
        credentials: HTTPAuthorizationCredentials | None = Depends(security),
    ) -> Principal:
        cfg: ServiceSettings = request.app.state.settings
        if cfg.auth_mode == "disabled":
            return Principal(subject="anonymous", scopes={"ledger.read", "ledger.write", "ops.metrics"})
        if credentials is None or credentials.scheme.lower() != "bearer":
            AUTH_FAILURE_COUNTER.labels(reason="missing_token").inc()
            raise ServiceError(status_code=401, code="missing_token", message="missing bearer token")
        try:
            payload = _decode_jwt(credentials.credentials, cfg)
        except ServiceError:
            raise
        except Exception:
            AUTH_FAILURE_COUNTER.labels(reason="invalid_token").inc()
            raise ServiceError(status_code=401, code="invalid_token", message="invalid bearer token")
        subject = str(payload.get("sub", "")).strip()
        if not subject:
            AUTH_FAILURE_COUNTER.labels(reason="missing_subject").inc()
            raise ServiceError(status_code=401, code="invalid_token", message="token subject is required")
        return Principal(subject=subject, scopes=_scope_set(payload))

    def authorize(scope: str, *, bucket: str):
        def dependency(request: Request, principal: Principal = Depends(get_principal)) -> Principal:
            cfg: ServiceSettings = request.app.state.settings
            request_key = principal.subject or (request.client.host if request.client else "anonymous")
            limit = cfg.write_rps if bucket == "write" else cfg.read_rps
            if not request.app.state.rate_limiter.allow(key=f"{bucket}:{request_key}", limit=limit):
                RATE_LIMIT_COUNTER.labels(bucket=bucket).inc()
                raise ServiceError(status_code=429, code="rate_limited", message="rate limit exceeded")
            if scope not in principal.scopes:
                AUTH_FAILURE_COUNTER.labels(reason="insufficient_scope").inc()
                raise ServiceError(status_code=403, code="insufficient_scope", message=f"missing scope: {scope}")
            return principal

        return dependency

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = request.headers.get("X-Request-Id", "").strip() or uuid4().hex
        route_label = request.url.path
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception as exc:
            if isinstance(exc, ServiceError):
                status_code = exc.status_code
                response = service_error_response(
                    request,
                    status_code=exc.status_code,
                    code=exc.code,
                    message=exc.message,
                )
            else:
                status_code = 500
                response = service_error_response(
                    request,
                    status_code=500,
                    code="internal_error",
                    message="internal server error",
                )
        duration = time.perf_counter() - started
        response.headers["X-Request-Id"] = request.state.request_id
        REQUEST_COUNTER.labels(method=request.method, route=route_label, status_code=str(status_code)).inc()
        REQUEST_LATENCY.labels(method=request.method, route=route_label).observe(duration)
        app.state.logger.info(
            json.dumps(
                {
                    "request_id": request.state.request_id,
                    "method": request.method,
                    "route": route_label,
                    "status_code": status_code,
                    "latency_ms": round(duration * 1000, 3),
                },
                sort_keys=True,
            )
        )
        return response

    @app.exception_handler(ServiceError)
    async def handle_service_error(request: Request, exc: ServiceError) -> JSONResponse:
        return service_error_response(request, status_code=exc.status_code, code=exc.code, message=exc.message)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return service_error_response(
            request,
            status_code=400,
            code="validation_error",
            message=str(exc),
        )

    @app.exception_handler(HTTPException)
    async def handle_http_exception(request: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else json.dumps(exc.detail, sort_keys=True)
        return service_error_response(
            request,
            status_code=exc.status_code,
            code="http_error",
            message=detail,
        )

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> dict[str, str]:
        if not app.state.ledger.is_ready():
            raise ServiceError(
                status_code=503,
                code="not_ready",
                message=app.state.ledger.last_ready_error or "database not ready",
            )
        return {"status": "ready"}

    @app.get("/metrics")
    def metrics(_: Principal = Depends(authorize("ops.metrics", bucket="read"))) -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.post(
        "/transactions/post",
        response_model=TxnResponse,
        responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 429: {"model": ErrorResponse}},
    )
    def post_transaction(
        request: PostRequest,
        _: Principal = Depends(authorize("ledger.write", bucket="write")),
    ) -> TxnResponse:
        return app.state.ledger.post(request)

    @app.post(
        "/transactions/reverse",
        response_model=TxnResponse,
        responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 429: {"model": ErrorResponse}},
    )
    def reverse_transaction(
        request: ReverseRequest,
        _: Principal = Depends(authorize("ledger.write", bucket="write")),
    ) -> TxnResponse:
        return app.state.ledger.reverse(request)

    @app.get(
        "/accounts/{account_id}/balance",
        response_model=BalanceResponse,
        responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 429: {"model": ErrorResponse}},
    )
    def get_balance(
        account_id: str,
        _: Principal = Depends(authorize("ledger.read", bucket="read")),
    ) -> BalanceResponse:
        return BalanceResponse(account_id=_account_id(account_id), balance_cents=app.state.ledger.balance(account_id))

    @app.post(
        "/replay/execute",
        responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    )
    def replay_execute(
        request: ReplayRequest,
        _: Principal = Depends(authorize("ledger.write", bucket="write")),
    ) -> dict[str, list[dict]]:
        try:
            results = [item.model_dump() for item in app.state.ledger.replay(request.operations)]
        except (ValidationError, ValueError) as exc:
            raise ServiceError(status_code=400, code="replay_invalid", message=str(exc)) from exc
        return {"results": results}

    @app.post(
        "/batch/reconcile/run",
        response_model=ReconcileResponse,
        responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    )
    def run_reconcile(
        payload: dict[str, str],
        _: Principal = Depends(authorize("ledger.write", bucket="write")),
    ) -> ReconcileResponse:
        business_date = str(payload.get("business_date", "")).strip()
        if not business_date:
            raise ServiceError(status_code=400, code="business_date_required", message="business_date is required")
        report = app.state.ledger.reconcile(business_date=business_date)
        return ReconcileResponse(**report)

    @app.get(
        "/batch/reconcile/{run_id}/report",
        response_model=ReconcileResponse,
        responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    )
    def get_reconcile(
        run_id: str,
        _: Principal = Depends(authorize("ledger.read", bucket="read")),
    ) -> ReconcileResponse:
        report = app.state.ledger.get_reconcile_report(run_id=run_id)
        if report is None:
            raise ServiceError(status_code=404, code="reconcile_not_found", message=f"run_id not found: {run_id}")
        return ReconcileResponse(**report)

    return app


app = build_app()
ledger = app.state.ledger


def main() -> None:
    host = os.environ.get("COBOL_GUARD_SERVICE_HOST", "127.0.0.1")
    port = int(os.environ.get("COBOL_GUARD_SERVICE_PORT", "8000"))
    uvicorn.run("cobol_guard.candidate.service:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
