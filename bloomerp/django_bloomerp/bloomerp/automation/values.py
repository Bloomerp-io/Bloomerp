import re
from typing import Any


TEMPLATE_PATTERN = re.compile(r"{{\s*([^}]+?)\s*}}")


def get_path_value(source: Any, path: str) -> Any:
    """Resolve dotted paths against dicts, lists, and model-like objects."""
    current = source
    for segment in path.split("."):
        if current is None:
            return None

        if isinstance(current, dict):
            current = current.get(segment)
            continue

        if isinstance(current, (list, tuple)) and segment.isdigit():
            index = int(segment)
            current = current[index] if index < len(current) else None
            continue

        current = getattr(current, segment, None)

    return current


def resolve_value(value: Any, input_data: dict) -> Any:
    """Resolve workflow parameter values against the current node input."""
    if isinstance(value, dict):
        if value.get("source") == "input" and value.get("path"):
            return get_path_value(input_data, value["path"])
        return {key: resolve_value(item, input_data) for key, item in value.items()}

    if isinstance(value, list):
        return [resolve_value(item, input_data) for item in value]

    if not isinstance(value, str):
        return value

    matches = list(TEMPLATE_PATTERN.finditer(value))
    if not matches:
        return value

    if len(matches) == 1 and matches[0].span() == (0, len(value)):
        return get_path_value({"input": input_data}, matches[0].group(1))

    def replace_match(match: re.Match) -> str:
        resolved = get_path_value({"input": input_data}, match.group(1))
        return "" if resolved is None else str(resolved)

    return TEMPLATE_PATTERN.sub(replace_match, value)


def resolve_parameters(parameters: dict | None, input_data: dict) -> dict:
    return resolve_value(parameters or {}, input_data)


def stringify_value(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, list):
        return "\n".join(stringify_value(item) for item in value)

    if isinstance(value, dict):
        return ", ".join(
            f"{key}: {stringify_value(item)}"
            for key, item in value.items()
        )

    return str(value)
