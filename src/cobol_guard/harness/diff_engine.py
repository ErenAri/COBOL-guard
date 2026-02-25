from __future__ import annotations

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
    diffs: list[FieldDiff]

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline_dir": self.baseline_dir,
            "candidate_dir": self.candidate_dir,
            "total_baseline_records": self.total_baseline_records,
            "changed_records": self.changed_records,
            "changed_records_ratio": self.changed_records_ratio,
            "changed_fields": self.changed_fields,
            "diffs": [item.to_dict() for item in self.diffs],
        }


def diff_runs(baseline_dir: Path, candidate_dir: Path) -> DiffReport:
    diffs: list[FieldDiff] = []
    changed_fields: set[str] = set()
    changed_record_keys: set[str] = set()
    total_baseline_records = 0

    for artifact, schema_id in ARTIFACT_SCHEMA_MAP.items():
        schema = load_schema(schema_id=schema_id, version_hint="1")
        baseline_records = read_fixed_width_records(path=baseline_dir / artifact, schema=schema)
        candidate_records = read_fixed_width_records(path=candidate_dir / artifact, schema=schema)
        baseline_records = sorted(baseline_records, key=lambda rec: canonical_sort_key(rec, schema=schema))
        candidate_records = sorted(candidate_records, key=lambda rec: canonical_sort_key(rec, schema=schema))
        total_baseline_records += len(baseline_records)

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

    changed_records = len(changed_record_keys)
    denominator = total_baseline_records if total_baseline_records > 0 else 1
    return DiffReport(
        baseline_dir=str(baseline_dir),
        candidate_dir=str(candidate_dir),
        total_baseline_records=total_baseline_records,
        changed_records=changed_records,
        changed_records_ratio=changed_records / denominator,
        changed_fields=sorted(changed_fields),
        diffs=diffs,
    )
