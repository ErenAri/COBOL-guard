from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

import yaml

from cobol_guard.constants import SCHEMA_REGISTRY_DIR


@dataclass(frozen=True, slots=True)
class SchemaField:
    name: str
    length: int
    field_type: str
    signed: bool


@dataclass(frozen=True, slots=True)
class SchemaDefinition:
    schema_id: str
    version: str
    fields: tuple[SchemaField, ...]
    primary_key_fields: tuple[str, ...]
    canonical_sort_key_fields: tuple[str, ...]
    record_fingerprint_fields: tuple[str, ...]
    money_fields: tuple[str, ...]
    nullability_defaults: dict[str, Any]
    canonical_byte_encoding_rules: dict[str, Any]
    hash_algorithm_version: str
    encoding_spec: dict[str, Any]

    @property
    def total_length(self) -> int:
        return sum(field.length for field in self.fields)


def _schema_file(schema_id: str, version_hint: str | None) -> Path:
    if version_hint is None:
        candidates = sorted(SCHEMA_REGISTRY_DIR.glob(f"{schema_id}.v*.yml"))
        if not candidates:
            raise FileNotFoundError(f"No schema files found for {schema_id}")
        return candidates[-1]
    major = version_hint.split(".")[0]
    candidate = SCHEMA_REGISTRY_DIR / f"{schema_id}.v{major}.yml"
    if not candidate.exists():
        raise FileNotFoundError(f"Schema file not found: {candidate}")
    return candidate


def load_schema(schema_id: str, version_hint: str | None = None) -> SchemaDefinition:
    path = _schema_file(schema_id=schema_id, version_hint=version_hint)
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    fields = tuple(
        SchemaField(
            name=str(item["name"]),
            length=int(item["length"]),
            field_type=str(item["type"]),
            signed=bool(item.get("signed", False)),
        )
        for item in payload["record_layout"]
    )
    return SchemaDefinition(
        schema_id=str(payload["schema_id"]),
        version=str(payload["version"]),
        fields=fields,
        primary_key_fields=tuple(payload["primary_key_fields"]),
        canonical_sort_key_fields=tuple(payload["canonical_sort_key_fields"]),
        record_fingerprint_fields=tuple(payload["record_fingerprint_fields"]),
        money_fields=tuple(payload.get("money_fields", [])),
        nullability_defaults=dict(payload.get("nullability_defaults", {})),
        canonical_byte_encoding_rules=dict(payload["canonical_byte_encoding_rules"]),
        hash_algorithm_version=str(payload["hash_algorithm_version"]),
        encoding_spec=dict(payload["encoding_spec"]),
    )


def materialize_defaults(record: dict[str, Any], schema: SchemaDefinition) -> dict[str, Any]:
    merged = dict(schema.nullability_defaults)
    merged.update(record)
    return merged


def _encode_int64(value: int, field: SchemaField) -> str:
    if field.signed:
        width = field.length - 1
        sign = "+" if value >= 0 else "-"
        digits = str(abs(value)).zfill(width)
        if len(digits) > width:
            raise ValueError(f"Value {value} exceeds schema field width {field.length}: {field.name}")
        return f"{sign}{digits}"
    digits = str(value).zfill(field.length)
    if len(digits) > field.length:
        raise ValueError(f"Value {value} exceeds schema field width {field.length}: {field.name}")
    return digits


def _encode_string(value: Any, field: SchemaField) -> str:
    text = str(value if value is not None else "")
    if len(text) > field.length:
        return text[: field.length]
    return text.ljust(field.length)


def canonical_record_text(record: dict[str, Any], schema: SchemaDefinition) -> str:
    materialized = materialize_defaults(record=record, schema=schema)
    chunks: list[str] = []
    for field in schema.fields:
        value = materialized.get(field.name, "")
        if field.field_type == "int64":
            chunks.append(_encode_int64(int(value), field))
        elif field.field_type == "string":
            chunks.append(_encode_string(value, field))
        else:
            raise ValueError(f"Unsupported schema field type: {field.field_type}")
    return "".join(chunks)


def canonical_record_bytes(record: dict[str, Any], schema: SchemaDefinition) -> bytes:
    charset = schema.encoding_spec.get("charset", "utf-8")
    return canonical_record_text(record=record, schema=schema).encode(charset)


def parse_record_text(line: str, schema: SchemaDefinition) -> dict[str, Any]:
    if len(line) < schema.total_length:
        raise ValueError(
            f"Line length {len(line)} shorter than schema length {schema.total_length} for {schema.schema_id}"
        )
    cursor = 0
    parsed: dict[str, Any] = {}
    for field in schema.fields:
        slice_text = line[cursor : cursor + field.length]
        cursor += field.length
        if field.field_type == "int64":
            if field.signed:
                sign = -1 if slice_text[0] == "-" else 1
                parsed[field.name] = sign * int(slice_text[1:])
            else:
                parsed[field.name] = int(slice_text)
        else:
            parsed[field.name] = slice_text.rstrip()
    return parsed


def record_fingerprint(record: dict[str, Any], schema: SchemaDefinition) -> str:
    payload = schema.version.encode("utf-8") + canonical_record_bytes(record=record, schema=schema)
    return sha256(payload).hexdigest()


def canonical_sort_key(record: dict[str, Any], schema: SchemaDefinition) -> tuple[Any, ...]:
    materialized = materialize_defaults(record=record, schema=schema)
    keys: list[Any] = []
    for field_name in schema.canonical_sort_key_fields:
        keys.append(materialized.get(field_name, ""))
    for field_name in schema.primary_key_fields:
        keys.append(materialized.get(field_name, ""))
    keys.append(record_fingerprint(record=materialized, schema=schema))
    return tuple(keys)
