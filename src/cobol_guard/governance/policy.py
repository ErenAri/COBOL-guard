from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(slots=True)
class GateDecision:
    passed: bool
    blockers: list[str]
    criticals: list[str]
    majors: list[str]
    minors: list[str]


def load_policy(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def classify_field(field_name: str, policy: dict[str, Any]) -> str:
    rules = policy["severity_rules"]
    if field_name in set(rules.get("blocker_fields", [])):
        return "BLOCKER"
    if field_name in set(rules.get("critical_fields", [])):
        return "CRITICAL"
    if field_name in set(rules.get("minor_fields", [])):
        return "MINOR"
    return "MAJOR"


def evaluate_gate(
    changed_records_ratio: float,
    changed_fields: list[str],
    changed_conditions: list[str] | None,
    invariant_failures: list[str],
    policy: dict[str, Any],
    change_class: str,
) -> GateDecision:
    blockers: list[str] = []
    criticals: list[str] = []
    majors: list[str] = []
    minors: list[str] = []
    allowed_change_classes = set(policy["rebless"]["allowed_change_classes"])
    if change_class not in allowed_change_classes:
        blockers.append(f"change_class_not_allowed:{change_class}")

    threshold = float(policy["blast_radius"]["max_changed_records_ratio"])
    override_class = str(policy["blast_radius"]["override_change_class"])
    if changed_records_ratio > threshold and change_class != override_class:
        blockers.append(
            f"blast_radius_exceeded:ratio={changed_records_ratio:.6f} threshold={threshold:.6f} change_class={change_class}"
        )

    for field_name in changed_fields:
        severity = classify_field(field_name=field_name, policy=policy)
        entry = f"{severity}:{field_name}"
        if severity == "BLOCKER":
            blockers.append(entry)
        elif severity == "CRITICAL":
            criticals.append(entry)
        elif severity == "MAJOR":
            majors.append(entry)
        else:
            minors.append(entry)

    major_conditions = set(policy["severity_rules"].get("major_conditions", []))
    for condition in changed_conditions or []:
        if condition in major_conditions:
            majors.append(f"MAJOR_CONDITION:{condition}")

    for failed_invariant in invariant_failures:
        blockers.append(f"invariant_failed:{failed_invariant}")

    passed = not blockers and not criticals and not majors
    return GateDecision(
        passed=passed,
        blockers=sorted(set(blockers)),
        criticals=sorted(set(criticals)),
        majors=sorted(set(majors)),
        minors=sorted(set(minors)),
    )
