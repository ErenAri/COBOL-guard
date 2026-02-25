from __future__ import annotations

import hashlib
import json
import random
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from cobol_guard.batch.runner import execute_checkpointed_v2_batch
from cobol_guard.candidate.engine import LedgerEngine
from cobol_guard.candidate.service import CandidateLedger, PostRequest, ReverseRequest
from cobol_guard.constants import RUNS_DIR
from cobol_guard.contracts import Transaction


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    index = max(0, min(len(sorted_values) - 1, int(round((q / 100.0) * (len(sorted_values) - 1)))))
    return float(sorted_values[index])


def _seed_to_int(seed: str) -> int:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def load_benchmark_profile(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def generate_synthetic_transactions(count: int, business_date: str, seed: str) -> list[Transaction]:
    rng = random.Random(_seed_to_int(seed))
    txns: list[Transaction] = []
    posted_ids: list[str] = []
    for idx in range(count):
        event_time = f"{business_date}120000"
        if posted_ids and idx % 10 == 0:
            original_id = posted_ids[rng.randrange(len(posted_ids))]
            request_id = f"REV{idx:013d}"
            account_id = f"ACC{rng.randrange(1, 1000):09d}"
            # Use same account as original reference if possible for valid reversal behavior.
            for prior in reversed(txns):
                if prior.request_id == original_id:
                    account_id = prior.account_id
                    break
            txns.append(
                Transaction(
                    request_id=request_id,
                    operation="REVERSE",
                    original_request_id=original_id,
                    account_id=account_id,
                    amount_cents=0,
                    business_date=business_date,
                    event_time=event_time,
                )
            )
            continue

        request_id = f"REQ{idx:013d}"
        account_id = f"ACC{rng.randrange(1, 1000):09d}"
        amount_cents = rng.randrange(100, 50000)
        txns.append(
            Transaction(
                request_id=request_id,
                operation="POST",
                original_request_id="",
                account_id=account_id,
                amount_cents=amount_cents,
                business_date=business_date,
                event_time=event_time,
            )
        )
        posted_ids.append(request_id)
    return txns


def benchmark_transaction_path(operations: int, business_date: str, seed: str) -> dict[str, Any]:
    rng = random.Random(_seed_to_int(seed + ":txn"))
    ledger = CandidateLedger()
    post_ids: list[tuple[str, str]] = []
    durations_ms: list[float] = []
    start_total = time.perf_counter()
    for idx in range(operations):
        if post_ids and idx % 10 == 0:
            original_request_id, account_id = post_ids[rng.randrange(len(post_ids))]
            reverse_request_id = f"REVAPI{idx:010d}"
            req = ReverseRequest(
                reverse_request_id=reverse_request_id,
                original_request_id=original_request_id,
                account_id=account_id,
                business_date=business_date,
                event_time=f"{business_date}101010",
            )
            started = time.perf_counter_ns()
            ledger.reverse(req)
            ended = time.perf_counter_ns()
            durations_ms.append((ended - started) / 1_000_000.0)
            continue

        request_id = f"REQAPI{idx:010d}"
        account_id = f"ACC{rng.randrange(1, 1000):09d}"
        amount_cents = rng.randrange(100, 50000)
        req = PostRequest(
            request_id=request_id,
            account_id=account_id,
            amount_cents=amount_cents,
            business_date=business_date,
            event_time=f"{business_date}101010",
        )
        started = time.perf_counter_ns()
        ledger.post(req)
        ended = time.perf_counter_ns()
        durations_ms.append((ended - started) / 1_000_000.0)
        post_ids.append((request_id, account_id))

    total_seconds = max(time.perf_counter() - start_total, 1e-9)
    tps = operations / total_seconds
    return {
        "operations": operations,
        "duration_seconds": total_seconds,
        "tps": tps,
        "p95_ms": _percentile(durations_ms, 95.0),
        "p99_ms": _percentile(durations_ms, 99.0),
    }


def benchmark_batch_path(
    records: int,
    chunk_size: int,
    business_date: str,
    seed: str,
) -> dict[str, Any]:
    transactions = generate_synthetic_transactions(count=records, business_date=business_date, seed=seed + ":batch")

    started = time.perf_counter()
    engine = LedgerEngine()
    result = engine.process(transactions=transactions, business_date=business_date)
    duration_seconds = max(time.perf_counter() - started, 1e-9)
    records_per_second = records / duration_seconds

    run_id = f"benchmark_restart_{uuid4().hex[:8]}"
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    failed_once = False
    try:
        execute_checkpointed_v2_batch(
            run_id=run_id,
            business_date=business_date,
            transactions=transactions,
            run_dir=run_dir,
            chunk_size=chunk_size,
            resume=False,
            fail_after_chunks=1,
        )
    except RuntimeError:
        failed_once = True
    resumed = execute_checkpointed_v2_batch(
        run_id=run_id,
        business_date=business_date,
        transactions=transactions,
        run_dir=run_dir,
        chunk_size=chunk_size,
        resume=True,
    )

    return {
        "records_processed": records,
        "duration_seconds": duration_seconds,
        "records_per_second": records_per_second,
        "closing_total_cents": result.totals.closing_total_cents,
        "chunk_size": chunk_size,
        "restart_injected_failure": failed_once,
        "restart_rework_chunks": resumed.reworked_chunks,
    }


def run_benchmark(case_payload: dict[str, Any], profile_payload: dict[str, Any]) -> dict[str, Any]:
    business_date = str(case_payload["business_date"])
    seed_id = str(case_payload["seed_id"])
    workload = dict(profile_payload.get("workload", {}))
    txn_operations = int(workload.get("txn_operations", 20000))
    batch_records = int(workload.get("batch_records", 100000))
    chunk_size = int(workload.get("chunk_size", 10000))

    txn_metrics = benchmark_transaction_path(operations=txn_operations, business_date=business_date, seed=seed_id)
    batch_metrics = benchmark_batch_path(
        records=batch_records,
        chunk_size=chunk_size,
        business_date=business_date,
        seed=seed_id,
    )
    return {
        "profile_id": profile_payload.get("profile_id", "unknown"),
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "candidate_v2": txn_metrics,
        "batch": batch_metrics,
    }


def evaluate_benchmark_gates(benchmark_report: dict[str, Any], policy: dict[str, Any]) -> list[str]:
    violations: list[str] = []
    performance = dict(policy.get("performance", {}))
    v2_policy = dict(performance.get("candidate_v2", {}))
    batch_policy = dict(performance.get("batch", {}))
    v2_metrics = dict(benchmark_report.get("candidate_v2", {}))
    batch_metrics = dict(benchmark_report.get("batch", {}))

    tps_min = float(v2_policy.get("txn_tps_min", 0.0))
    p95_max = float(v2_policy.get("txn_p95_ms_max", float("inf")))
    p99_max = float(v2_policy.get("txn_p99_ms_max", float("inf")))
    if float(v2_metrics.get("tps", 0.0)) < tps_min:
        violations.append(f"v2_tps_below_min:{v2_metrics.get('tps', 0.0):.2f}<{tps_min:.2f}")
    if float(v2_metrics.get("p95_ms", 0.0)) > p95_max:
        violations.append(f"v2_p95_exceeds_max:{v2_metrics.get('p95_ms', 0.0):.2f}>{p95_max:.2f}")
    if float(v2_metrics.get("p99_ms", 0.0)) > p99_max:
        violations.append(f"v2_p99_exceeds_max:{v2_metrics.get('p99_ms', 0.0):.2f}>{p99_max:.2f}")

    records_min = int(batch_policy.get("records_min", 0))
    duration_max = float(batch_policy.get("duration_seconds_max", float("inf")))
    restart_max_rework = int(batch_policy.get("restart_rework_chunks_max", 1_000_000))
    if int(batch_metrics.get("records_processed", 0)) < records_min:
        violations.append(f"batch_records_below_min:{batch_metrics.get('records_processed', 0)}<{records_min}")
    if float(batch_metrics.get("duration_seconds", 0.0)) > duration_max:
        violations.append(
            f"batch_duration_exceeds_max:{batch_metrics.get('duration_seconds', 0.0):.2f}>{duration_max:.2f}"
        )
    if int(batch_metrics.get("restart_rework_chunks", 0)) > restart_max_rework:
        violations.append(
            f"batch_rework_chunks_exceeds_max:{batch_metrics.get('restart_rework_chunks', 0)}>{restart_max_rework}"
        )
    return violations


def write_benchmark_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
