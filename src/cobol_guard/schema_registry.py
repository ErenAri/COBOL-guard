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


REQUIRED_SCHEMA_KEYS = (
    "schema_id",
    "version",
    "record_layout",
    "encoding_spec",
    "primary_key_fields",
    "canonical_sort_key_fields",
    "record_fingerprint_fields",
    "money_fields",
    "nullability_defaults",
    "canonicalization_spec_version",
    "canonical_byte_encoding_rules",
    "compatibility_policy",
    "hash_algorithm_version",
)


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


def _require_schema_keys(payload: dict[str, Any], path: Path) -> None:
    missing = [key for key in REQUIRED_SCHEMA_KEYS if key not in payload]
    if missing:
        raise ValueError(f"Schema {path} missing required keys: {', '.join(sorted(missing))}")


def _validate_layout(layout: list[dict[str, Any]], path: Path) -> None:
    expected_offset = 1
    names: set[str] = set()
    for item in layout:
        name = str(item["name"])
        if name in names:
            raise ValueError(f"Schema {path} has duplicate field in record_layout: {name}")
        names.add(name)
        offset = int(item.get("offset", expected_offset))
        length = int(item["length"])
        if offset != expected_offset:
            raise ValueError(
                f"Schema {path} has non-contiguous offsets at {name}: expected {expected_offset}, found {offset}"
            )
        if length <= 0:
            raise ValueError(f"Schema {path} has non-positive length for field {name}: {length}")
        expected_offset += length


def _validate_references(payload: dict[str, Any], field_names: set[str], path: Path) -> None:
    for ref_name in (
        "primary_key_fields",
        "canonical_sort_key_fields",
        "record_fingerprint_fields",
        "money_fields",
    ):
        refs = [str(item) for item in payload.get(ref_name, [])]
        unknown = sorted(set(refs) - field_names)
        if unknown:
            raise ValueError(f"Schema {path} has unknown field references in {ref_name}: {', '.join(unknown)}")


def _validate_canonical_rules(payload: dict[str, Any], path: Path) -> None:
    encoding = dict(payload["encoding_spec"])
    charset = str(encoding.get("charset", "utf-8")).lower()
    newline = str(encoding.get("newline", "lf")).lower()
    if charset != "utf-8":
        raise ValueError(f"Schema {path} must use utf-8 charset, found: {charset}")
    if newline != "lf":
        raise ValueError(f"Schema {path} must use lf newlines, found: {newline}")

    rules = dict(payload["canonical_byte_encoding_rules"])
    int64_rules = dict(rules.get("int64", {}))
    string_rules = dict(rules.get("string", {}))
    if str(int64_rules.get("signed", "leading_sign")) != "leading_sign":
        raise ValueError(f"Schema {path} int64.signed must be leading_sign")
    if not bool(int64_rules.get("zero_pad", True)):
        raise ValueError(f"Schema {path} int64.zero_pad must be true")
    pad_char = str(string_rules.get("pad_char", " "))
    if len(pad_char) != 1:
        raise ValueError(f"Schema {path} string.pad_char must be a single character")
    align = str(string_rules.get("align", "left")).lower()
    if align not in {"left", "right"}:
        raise ValueError(f"Schema {path} string.align must be left or right")


def load_schema(schema_id: str, version_hint: str | None = None) -> SchemaDefinition:
    path = _schema_file(schema_id=schema_id, version_hint=version_hint)
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    _require_schema_keys(payload=payload, path=path)
    _validate_layout(layout=list(payload["record_layout"]), path=path)
    fields = tuple(
        SchemaField(
            name=str(item["name"]),
            length=int(item["length"]),
            field_type=str(item["type"]),
            signed=bool(item.get("signed", False)),
        )
        for item in payload["record_layout"]
    )
    field_names = {field.name for field in fields}
    _validate_references(payload=payload, field_names=field_names, path=path)
    _validate_canonical_rules(payload=payload, path=path)
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


def _encode_int64(value: int, field: SchemaField, rules: dict[str, Any]) -> str:
    signed_rule = str(rules.get("signed", "leading_sign"))
    if signed_rule != "leading_sign":
        raise ValueError(f"Unsupported int64 signed rule: {signed_rule}")
    if not bool(rules.get("zero_pad", True)):
        raise ValueError("int64 zero_pad must be true for deterministic encoding")
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


def _encode_string(value: Any, field: SchemaField, rules: dict[str, Any]) -> str:
    text = str(value if value is not None else "")
    truncate = bool(rules.get("truncate", True))
    if len(text) > field.length:
        if truncate:
            text = text[: field.length]
        else:
            raise ValueError(f"Value for {field.name} exceeds fixed width {field.length}")

    pad_char = str(rules.get("pad_char", " "))
    if len(pad_char) != 1:
        raise ValueError(f"Invalid pad_char for {field.name}: {pad_char!r}")

    align = str(rules.get("align", "left")).lower()
    if align == "left":
        return text.ljust(field.length, pad_char)
    if align == "right":
        return text.rjust(field.length, pad_char)
    raise ValueError(f"Unsupported align rule for {field.name}: {align}")


def canonical_record_text(record: dict[str, Any], schema: SchemaDefinition) -> str:
    rules = dict(schema.canonical_byte_encoding_rules)
    field_order = str(rules.get("field_order", "record_layout"))
    if field_order != "record_layout":
        raise ValueError(f"Unsupported field_order for canonical serialization: {field_order}")
    if not bool(rules.get("null_materialization", True)):
        raise ValueError("null_materialization must be true for deterministic canonicalization")

    int64_rules = dict(rules.get("int64", {}))
    string_rules = dict(rules.get("string", {}))
    materialized = materialize_defaults(record=record, schema=schema)
    chunks: list[str] = []
    for field in schema.fields:
        value = materialized.get(field.name, "")
        if field.field_type == "int64":
            chunks.append(_encode_int64(int(value), field, rules=int64_rules))
        elif field.field_type == "string":
            chunks.append(_encode_string(value, field, rules=string_rules))
        else:
            raise ValueError(f"Unsupported schema field type: {field.field_type}")
    return "".join(chunks)


def canonical_record_bytes(record: dict[str, Any], schema: SchemaDefinition) -> bytes:
    charset = str(schema.encoding_spec.get("charset", "utf-8")).lower()
    if charset != "utf-8":
        raise ValueError(f"Unsupported charset for canonical_record_bytes: {charset}")
    return canonical_record_text(record=record, schema=schema).encode("utf-8")


def parse_record_text(line: str, schema: SchemaDefinition) -> dict[str, Any]:
    if len(line) < schema.total_length:
        line = line.ljust(schema.total_length)
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
    if schema.hash_algorithm_version != "sha256-v1":
        raise ValueError(f"Unsupported hash algorithm version: {schema.hash_algorithm_version}")
    materialized = materialize_defaults(record=record, schema=schema)
    included = set(schema.record_fingerprint_fields) if schema.record_fingerprint_fields else {f.name for f in schema.fields}
    projected: dict[str, Any] = {}
    for field in schema.fields:
        if field.name in included:
            projected[field.name] = materialized.get(field.name, "")
            continue
        projected[field.name] = 0 if field.field_type == "int64" else ""
    payload = schema.version.encode("utf-8") + canonical_record_bytes(record=projected, schema=schema)
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
