#!/usr/bin/env bash
set -euo pipefail

document-cotton-components() {
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  COTTON_DOCS_REPO_ROOT="$script_dir" python3 - "$@" <<'PY'
from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path


ROOT = Path(os.environ["COTTON_DOCS_REPO_ROOT"]).resolve()
COTTON_UI_DIR = ROOT / "bloomerp/django_bloomerp/bloomerp/templates/cotton/ui"
DOCS_DIR = ROOT / "docs/developers/cotton"


SECTION_ALIASES = {
    "parameters": "Parameters",
    "parameter": "Parameters",
    "params": "Parameters",
    "props": "Parameters",
    "variables": "Parameters",
    "vars": "Parameters",
    "args": "Parameters",
    "arguments": "Parameters",
    "slots": "Slots",
    "slot": "Slots",
    "examples": "Examples",
    "example": "Examples",
    "notes": "Notes",
    "note": "Notes",
}


COMMENT_RE = re.compile(r"{%\s*comment\s*%}(.*?){%\s*endcomment\s*%}", re.DOTALL)
BLOOMERP_COMPONENT_RE = re.compile(r"""bloomerp-component\s*=\s*["']([^"']+)["']""")


def component_tag(source_path: Path) -> str:
    rel = source_path.relative_to(COTTON_UI_DIR).with_suffix("")
    return "c-ui." + ".".join(rel.parts)


def clean_comment(raw: str) -> list[str]:
    lines = []
    for line in raw.splitlines():
        cleaned = line.rstrip()
        if cleaned.lstrip().startswith("*"):
            cleaned = cleaned.lstrip()[1:].strip()
        lines.append(cleaned)
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return lines


def split_sections(lines: list[str]) -> tuple[list[str], dict[str, list[str]]]:
    description: list[str] = []
    sections: dict[str, list[str]] = {}
    current_name: str | None = None

    for line in lines:
        stripped = line.strip()
        section_match = re.match(r"^([A-Za-z][A-Za-z _-]*):\s*$", stripped)
        if section_match:
            key = section_match.group(1).strip().lower().replace(" ", "_").replace("-", "_")
            current_name = SECTION_ALIASES.get(key, section_match.group(1).strip().title())
            sections.setdefault(current_name, [])
            continue

        if current_name:
            sections[current_name].append(line)
        else:
            description.append(line)

    return description, sections


def parse_bullet(line: str) -> tuple[str, str, str] | None:
    if not line.startswith("-"):
        return None

    content = line[1:].strip()
    if not content:
        return None

    match = re.match(r"`?([A-Za-z_][\w-]*)`?\s*(?:\(([^)]*)\))?\s*(?::|-)\s*(.*)$", content)
    if match:
        return match.group(1), match.group(2) or "", match.group(3).strip()

    return content, "", ""


def markdown_table(section_lines: list[str], fallback_heading: str) -> str:
    rows = []
    extras = []

    for line in section_lines:
        if not line.strip():
            continue
        parsed = parse_bullet(line)
        if parsed:
            rows.append(parsed)
        else:
            extras.append(line)

    if not rows:
        return "\n".join(section_lines).strip()

    out = [
        "| Name | Type | Description |",
        "| --- | --- | --- |",
    ]
    for name, type_name, description in rows:
        out.append(f"| `{name}` | {type_name or '-'} | {description or '-'} |")

    if extras:
        out.extend(["", "Additional details:", "", *extras])

    return "\n".join(out).strip()


def render_doc(source_path: Path) -> str:
    text = source_path.read_text(encoding="utf-8")
    tag = component_tag(source_path)
    component_name = source_path.relative_to(COTTON_UI_DIR).with_suffix("").parts[-1]
    rel_source = source_path.relative_to(ROOT)
    hydrated_components = BLOOMERP_COMPONENT_RE.findall(text)

    comment_match = COMMENT_RE.search(text)
    if comment_match:
        comment_lines = clean_comment(comment_match.group(1))
        description, sections = split_sections(comment_lines)
    else:
        comment_lines = []
        description = []
        sections = {}

    description_lines = [
        line.strip()
        for line in description
        if line.strip()
    ]
    if description_lines and description_lines[0] == component_name:
        description_lines = description_lines[1:]

    if not comment_match:
        body_description = "No component docstring found."
    elif description_lines:
        body_description = "\n".join(description_lines).strip()
    else:
        body_description = "No additional description provided."

    out = [
        f"# `{tag}`",
        "",
        f"- Tag: `<{tag} />`",
        f"- Source: `{rel_source}`",
    ]

    if hydrated_components:
        unique_components = ", ".join(f"`{name}`" for name in dict.fromkeys(hydrated_components))
        out.append(f"- TypeScript component id: {unique_components}")

    out.extend(["", "## Description", "", body_description])

    for section_name, section_lines in sections.items():
        if section_name in {"Parameters", "Slots"}:
            rendered = markdown_table(section_lines, section_name)
        else:
            rendered = "\n".join(section_lines).strip()
        if not rendered:
            continue
        out.extend(["", f"## {section_name}", "", rendered])

    if not comment_lines:
        out.extend([
            "",
            "## Documentation Status",
            "",
            "Add a `{% comment %}` block at the top of the component template to populate this page.",
        ])

    return "\n".join(out).rstrip() + "\n"


def write_index(component_docs: list[tuple[str, Path, Path]]) -> None:
    lines = [
        "# Cotton UI Components",
        "",
        "Generated from Django Cotton component docstrings in `bloomerp/django_bloomerp/bloomerp/templates/cotton/ui`.",
        "",
        "Run `./scripts.sh document-cotton-components` to regenerate these docs.",
        "",
        "## Components",
        "",
    ]

    for tag, _, doc_path in sorted(component_docs):
        rel_doc = doc_path.relative_to(DOCS_DIR)
        lines.append(f"- [`{tag}`]({rel_doc.as_posix()})")

    (DOCS_DIR / "index.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    if not COTTON_UI_DIR.exists():
        print(f"Missing Cotton UI directory: {COTTON_UI_DIR}", file=sys.stderr)
        return 1

    if DOCS_DIR.exists():
        shutil.rmtree(DOCS_DIR)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    component_docs: list[tuple[str, Path, Path]] = []
    for source_path in sorted(COTTON_UI_DIR.rglob("*.html")):
        rel = source_path.relative_to(COTTON_UI_DIR).with_suffix(".md")
        doc_path = DOCS_DIR / rel
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.write_text(render_doc(source_path), encoding="utf-8")
        component_docs.append((component_tag(source_path), source_path, doc_path))

    write_index(component_docs)
    print(f"Generated {len(component_docs)} Cotton UI component docs in {DOCS_DIR}")
    return 0


raise SystemExit(main())
PY
}

case "${1:-}" in
  document-cotton-components)
    shift
    document-cotton-components "$@"
    ;;
  ""|-h|--help|help)
    echo "Usage: ./scripts.sh document-cotton-components"
    ;;
  *)
    echo "Unknown command: $1" >&2
    echo "Usage: ./scripts.sh document-cotton-components" >&2
    exit 1
    ;;
esac
