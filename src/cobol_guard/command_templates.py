from __future__ import annotations

from string import Formatter


def render_command_template(
    command_template: str,
    *,
    required_fields: set[str],
    optional_fields: set[str] | None = None,
    values: dict[str, str],
) -> str:
    template = command_template.strip()
    if not template:
        raise ValueError("command_template is required")

    allowed_fields = set(required_fields)
    if optional_fields:
        allowed_fields.update(optional_fields)

    referenced_fields: set[str] = set()
    for _, field_name, _, _ in Formatter().parse(template):
        if field_name is None:
            continue
        if field_name == "":
            raise ValueError("positional placeholders are not supported in command templates")
        root_field = field_name.split(".", 1)[0].split("[", 1)[0]
        referenced_fields.add(root_field)

    missing = sorted(required_fields - referenced_fields)
    if missing:
        raise ValueError(f"command_template missing required placeholders: {', '.join(missing)}")

    unknown = sorted(referenced_fields - allowed_fields)
    if unknown:
        raise ValueError(f"command_template contains unsupported placeholders: {', '.join(unknown)}")

    return template.format(**values)
