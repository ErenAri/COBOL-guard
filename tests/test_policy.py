from pathlib import Path

from cobol_guard.governance.policy import evaluate_gate, load_policy


def test_money_field_diff_is_blocker() -> None:
    policy = load_policy(Path("governance/gate_policy.yml"))
    decision = evaluate_gate(
        changed_records_ratio=0.0001,
        changed_fields=["amount_cents"],
        changed_conditions=["field_mismatch"],
        invariant_failures=[],
        policy=policy,
        change_class="bug_fix",
    )
    assert not decision.passed
    assert any("BLOCKER:amount_cents" == item for item in decision.blockers)


def test_blast_radius_requires_override_change_class() -> None:
    policy = load_policy(Path("governance/gate_policy.yml"))
    decision = evaluate_gate(
        changed_records_ratio=0.01,
        changed_fields=[],
        changed_conditions=[],
        invariant_failures=[],
        policy=policy,
        change_class="bug_fix",
    )
    assert not decision.passed
    assert any("blast_radius_exceeded" in item for item in decision.blockers)


def test_missing_record_condition_is_major() -> None:
    policy = load_policy(Path("governance/gate_policy.yml"))
    decision = evaluate_gate(
        changed_records_ratio=0.0001,
        changed_fields=[],
        changed_conditions=["missing_record"],
        invariant_failures=[],
        policy=policy,
        change_class="bug_fix",
    )
    assert not decision.passed
    assert "MAJOR_CONDITION:missing_record" in decision.majors
