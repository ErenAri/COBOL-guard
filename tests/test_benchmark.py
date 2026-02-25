from pathlib import Path

from cobol_guard.governance.policy import load_policy
from cobol_guard.harness.benchmarking import evaluate_benchmark_gates


def test_evaluate_benchmark_gates_detects_failures() -> None:
    policy = load_policy(Path("governance/gate_policy.yml"))
    report = {
        "candidate_v2": {"tps": 10.0, "p95_ms": 999.0, "p99_ms": 999.0},
        "batch": {"records_processed": 100, "duration_seconds": 9999.0, "restart_rework_chunks": 99},
    }
    violations = evaluate_benchmark_gates(benchmark_report=report, policy=policy)
    assert any(item.startswith("v2_tps_below_min") for item in violations)
    assert any(item.startswith("batch_records_below_min") for item in violations)
