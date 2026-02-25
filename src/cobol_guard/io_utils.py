from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cobol_guard.schema_registry import (
    SchemaDefinition,
    canonical_record_text,
    canonical_sort_key,
    parse_record_text,
)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_fixed_width_records(path: Path, records: list[dict[str, Any]], schema: SchemaDefinition) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(records, key=lambda rec: canonical_sort_key(rec, schema))
    lines = [canonical_record_text(record=item, schema=schema) for item in ordered]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8", newline="\n")


def read_fixed_width_records(path: Path, schema: SchemaDefinition) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for raw in handle:
            line = raw.rstrip("\n")
            if not line:
                continue
            records.append(parse_record_text(line=line, schema=schema))
    return records
