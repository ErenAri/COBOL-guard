from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cobol_guard.io_utils import read_fixed_width_records
from cobol_guard.schema_registry import canonical_sort_key, load_schema

ARTIFACT_SCHEMA_MAP: dict[str, str] = {
    "ledger_journal.dat": "ledger_journal",
    "reconcile_totals.dat": "reconcile_totals",
    "exception_report.dat": "exception_report",
}


def _load_schema_versions(run_dir: Path) -> dict[str, str]:
    manifest_path = run_dir / "run_manifest.json"
    if not manifest_path.exists():
        return {}
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    schema_versions = payload.get("schema_versions", {})
    return {str(k): str(v) for k, v in dict(schema_versions).items()}


def _duplicate_sort_key_indexes(records: list[dict[str, Any]], schema) -> list[tuple[int, int]]:
    seen: dict[tuple[Any, ...], int] = {}
    duplicates: list[tuple[int, int]] = []
    for index, record in enumerate(records):
        key = canonical_sort_key(record, schema=schema)
        first = seen.get(key)
        if first is None:
            seen[key] = index
            continue
        duplicates.append((first, index))
    return duplicates


@dataclass(slots=True)
class FieldDiff:
    artifact: str
    record_index: int
    field_name: str
    baseline_value: Any
    candidate_value: Any
    condition: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact": self.artifact,
            "record_index": self.record_index,
            "field_name": self.field_name,
            "baseline_value": self.baseline_value,
            "candidate_value": self.candidate_value,
            "condition": self.condition,
        }


@dataclass(slots=True)
class DiffReport:
    baseline_dir: str
    candidate_dir: str
    total_baseline_records: int
    changed_records: int
    changed_records_ratio: float
    changed_fields: list[str]
    changed_conditions: list[str]
    diffs: list[FieldDiff]

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline_dir": self.baseline_dir,
            "candidate_dir": self.candidate_dir,
            "total_baseline_records": self.total_baseline_records,
            "changed_records": self.changed_records,
            "changed_records_ratio": self.changed_records_ratio,
            "changed_fields": self.changed_fields,
            "changed_conditions": self.changed_conditions,
            "diffs": [item.to_dict() for item in self.diffs],
        }


def diff_runs(baseline_dir: Path, candidate_dir: Path) -> DiffReport:
    diffs: list[FieldDiff] = []
    changed_fields: set[str] = set()
    changed_conditions: set[str] = set()
    changed_record_keys: set[str] = set()
    total_baseline_records = 0
    baseline_schema_versions = _load_schema_versions(run_dir=baseline_dir)
    candidate_schema_versions = _load_schema_versions(run_dir=candidate_dir)

    for artifact, schema_id in ARTIFACT_SCHEMA_MAP.items():
        baseline_schema_version = baseline_schema_versions.get(schema_id)
        candidate_schema_version = candidate_schema_versions.get(schema_id)
        if baseline_schema_versions or candidate_schema_versions:
            if baseline_schema_version != candidate_schema_version:
                key = f"{artifact}:schema_mismatch"
                changed_fields.add("_schema_version")
                changed_conditions.add("schema_mismatch")
                changed_record_keys.add(key)
                diffs.append(
                    FieldDiff(
                        artifact=artifact,
                        record_index=0,
                        field_name="_schema_version",
                        baseline_value=baseline_schema_version,
                        candidate_value=candidate_schema_version,
                        condition="schema_mismatch",
                    )
                )

        schema = load_schema(schema_id=schema_id, version_hint="1")
        baseline_records = read_fixed_width_records(path=baseline_dir / artifact, schema=schema)
        candidate_records = read_fixed_width_records(path=candidate_dir / artifact, schema=schema)
        baseline_records = sorted(baseline_records, key=lambda rec: canonical_sort_key(rec, schema=schema))
        candidate_records = sorted(candidate_records, key=lambda rec: canonical_sort_key(rec, schema=schema))
        total_baseline_records += len(baseline_records)

        for first_index, duplicate_index in _duplicate_sort_key_indexes(records=baseline_records, schema=schema):
            key = f"{artifact}:baseline_ordering:{duplicate_index}"
            changed_fields.add("_ordering")
            changed_conditions.add("ordering_violation")
            changed_record_keys.add(key)
            diffs.append(
                FieldDiff(
                    artifact=artifact,
                    record_index=duplicate_index,
                    field_name="_ordering",
                    baseline_value=f"duplicate_sort_key_first_index={first_index}",
                    candidate_value="baseline",
                    condition="ordering_violation",
                )
            )

        for first_index, duplicate_index in _duplicate_sort_key_indexes(records=candidate_records, schema=schema):
            key = f"{artifact}:candidate_ordering:{duplicate_index}"
            changed_fields.add("_ordering")
            changed_conditions.add("ordering_violation")
            changed_record_keys.add(key)
            diffs.append(
                FieldDiff(
                    artifact=artifact,
                    record_index=duplicate_index,
                    field_name="_ordering",
                    baseline_value="candidate",
                    candidate_value=f"duplicate_sort_key_first_index={first_index}",
                    condition="ordering_violation",
                )
            )

        max_len = max(len(baseline_records), len(candidate_records))
        for index in range(max_len):
            key = f"{artifact}:{index}"
            if index >= len(baseline_records):
                changed_fields.add("_record_presence")
                changed_record_keys.add(key)
                diffs.append(
                    FieldDiff(
                        artifact=artifact,
                        record_index=index,
                        field_name="_record_presence",
                        baseline_value=None,
                        candidate_value=candidate_records[index],
                        condition="missing_record",
                    )
                )
                changed_conditions.add("missing_record")
                continue

            if index >= len(candidate_records):
                changed_fields.add("_record_presence")
                changed_record_keys.add(key)
                diffs.append(
                    FieldDiff(
                        artifact=artifact,
                        record_index=index,
                        field_name="_record_presence",
                        baseline_value=baseline_records[index],
                        candidate_value=None,
                        condition="missing_record",
                    )
                )
                changed_conditions.add("missing_record")
                continue

            baseline_record = baseline_records[index]
            candidate_record = candidate_records[index]
            for field in schema.fields:
                baseline_value = baseline_record.get(field.name)
                candidate_value = candidate_record.get(field.name)
                if baseline_value != candidate_value:
                    changed_fields.add(field.name)
                    changed_record_keys.add(key)
                    diffs.append(
                        FieldDiff(
                            artifact=artifact,
                            record_index=index,
                            field_name=field.name,
                            baseline_value=baseline_value,
                            candidate_value=candidate_value,
                            condition="field_mismatch",
                        )
                    )
                    changed_conditions.add("field_mismatch")

    changed_records = len(changed_record_keys)
    denominator = total_baseline_records if total_baseline_records > 0 else 1
    return DiffReport(
        baseline_dir=str(baseline_dir),
        candidate_dir=str(candidate_dir),
        total_baseline_records=total_baseline_records,
        changed_records=changed_records,
        changed_records_ratio=changed_records / denominator,
        changed_fields=sorted(changed_fields),
        changed_conditions=sorted(changed_conditions),
        diffs=diffs,
    )
