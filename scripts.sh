#!/usr/bin/env bash
set -euo pipefail

update-internal-sdk() {
    local script_dir
    local django_root
    local sdk_dir

    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    django_root="$script_dir/bloomerp/django_bloomerp"
    sdk_dir="$django_root/bloomerp/static_src/ts/sdk"

    (
        cd "$django_root"
        uv run manage.py create_sdk "$sdk_dir" \
            --language typescript \
            --filename sdk.ts \
            --force \
            --skip-checks \
            --app bloomerp \
            "$@"
    )
}

reset-test-data() {
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

  cd "$script_dir/bloomerp/django_bloomerp"
  rm -f db.sqlite3
  uv run manage.py migrate
  uv run manage.py save_application_fields
  uv run manage.py create_test_data
}

sync-cli-config-settings() {
    local script_dir
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

  python3 - "$script_dir" "$@" <<'PY'
from __future__ import annotations

import argparse
import shutil
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from pprint import pformat


def unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def load_project_installed_apps(manifest_path: Path, legacy_settings_path: Path) -> list[str]:
    installed_apps: list[str] = []

    if manifest_path.is_file():
        data = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
        django_settings = data.get("django", {})
        if isinstance(django_settings, dict):
            apps = django_settings.get("installed_apps", [])
            if isinstance(apps, list):
                installed_apps.extend(
                    app
                    for app in apps
                    if isinstance(app, str) and app.strip()
                )

    # Preserve the development module app currently used by this repo.
    if legacy_settings_path.is_file():
        legacy_settings = legacy_settings_path.read_text(encoding="utf-8")
        if "'bloomerp_modules'" in legacy_settings or '"bloomerp_modules"' in legacy_settings:
            installed_apps.append("bloomerp_modules")

    return unique(installed_apps)


def copy_cli_config(template_config_dir: Path, target_config_dir: Path, *, backup: bool) -> Path | None:
    backup_root: Path | None = None
    if target_config_dir.exists() and backup:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        backup_root = target_config_dir.parent / ".bloomerp" / "config-sync-backups" / timestamp
        shutil.copytree(target_config_dir, backup_root / "config")

    if target_config_dir.exists():
        shutil.rmtree(target_config_dir)

    shutil.copytree(
        template_config_dir,
        target_config_dir,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )
    return backup_root


def render_project_registry(project_registry_path: Path, installed_apps: list[str]) -> None:
    source = project_registry_path.read_text(encoding="utf-8")
    rendered = source.replace(
        "__PROJECT_INSTALLED_APPS__",
        pformat(installed_apps, width=88, sort_dicts=False),
    )
    project_registry_path.write_text(rendered, encoding="utf-8")


def expected_snapshot(template_config_dir: Path, installed_apps: list[str]) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for path in sorted(template_config_dir.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        relative = path.relative_to(template_config_dir).as_posix()
        contents = path.read_text(encoding="utf-8")
        if relative == "settings/generated/project_registry.py":
            contents = contents.replace(
                "__PROJECT_INSTALLED_APPS__",
                pformat(installed_apps, width=88, sort_dicts=False),
            )
        snapshot[relative] = contents
    return snapshot


def check_sync(template_config_dir: Path, target_config_dir: Path, installed_apps: list[str]) -> int:
    expected = expected_snapshot(template_config_dir, installed_apps)
    actual: dict[str, str] = {}
    for path in sorted(target_config_dir.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        actual[path.relative_to(target_config_dir).as_posix()] = path.read_text(encoding="utf-8")

    drift = sorted(
        {
            *[key for key, value in expected.items() if actual.get(key) != value],
            *[key for key in actual if key not in expected],
        }
    )

    if drift:
        print("Config scaffold drift detected:")
        for path in drift:
            print(f"  - config/{path}")
        return 1

    print("Config scaffold is current.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="./scripts.sh sync-cli-config-settings",
        description="Sync bloomerp/django_bloomerp/config from CLI template_project/config.",
    )
    parser.add_argument("--check", action="store_true", help="Check drift without writing files.")
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Do not create a backup before replacing config.",
    )
    import sys

    args = parser.parse_args(sys.argv[2:])

    script_dir = Path(sys.argv[1]).resolve()
    django_root = script_dir / "bloomerp/django_bloomerp"
    template_config_dir = django_root / "bloomerp/cli/template_project/config"
    target_config_dir = django_root / "config"
    manifest_path = django_root / ".bloomerp/project.bloomerp.toml"
    legacy_settings_path = target_config_dir / "settings.py"

    if not template_config_dir.is_dir():
        raise SystemExit(f"Template config directory not found: {template_config_dir}")

    installed_apps = load_project_installed_apps(manifest_path, legacy_settings_path)
    if args.check:
        if not target_config_dir.exists():
            print("Config scaffold drift detected:")
            print("  - config/ (missing)")
            return 1
        return check_sync(template_config_dir, target_config_dir, installed_apps)

    backup_root = copy_cli_config(
        template_config_dir,
        target_config_dir,
        backup=not args.no_backup,
    )
    project_registry_path = target_config_dir / "settings/generated/project_registry.py"
    render_project_registry(project_registry_path, installed_apps)

    if backup_root is not None:
        print(f"Backed up previous config to {backup_root / 'config'}")
    print(f"Synced config scaffold from CLI template into {target_config_dir}")
    if installed_apps:
        print(f"Rendered project apps into project_registry.py: {installed_apps}")
    else:
        print("Rendered project apps into project_registry.py: []")
    return 0


raise SystemExit(main())
PY
}

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

autoCreateTests() {
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  python3 - "$script_dir" "$@" <<'PY'
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


TYPE_TO_BASE_CLASS = {
    "models": "BaseBloomerpModelTestCase",
    "views": "BaseBloomerpViewTestCase",
    "widgets": "BaseBloomerpWidgetTestCase",
    "components": "BaseBloomerpComponentTestCase",
}


def snake_to_pascal(value: str) -> str:
    return "".join(part.capitalize() for part in re.split(r"[_\-\s]+", value) if part)


def build_test_content(base_class: str, source_relative: Path) -> str:
    class_name = f"Test{snake_to_pascal(source_relative.stem)}"
    return (
        f"from bloomerp.tests.base import {base_class}\n\n\n"
        f"class {class_name}({base_class}):\n"
        "    def test_placeholder(self):\n"
        "        self.assertTrue(True)\n"
    )


def iter_source_files(source_root: Path):
    for file_path in sorted(source_root.rglob("*.py")):
        if file_path.name == "__init__.py":
            continue
        if "__pycache__" in file_path.parts:
            continue
        yield file_path


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="./scripts.sh autoCreateTests",
        description="Create missing test files for a source type.",
    )
    parser.add_argument(
        "--type",
        choices=sorted(TYPE_TO_BASE_CLASS.keys()),
        required=True,
        help="Source type folder to scaffold tests for.",
    )
    args = parser.parse_args(argv)

    script_dir = Path(sys.argv[1]).resolve()
    bloomerp_dir = script_dir / "bloomerp/django_bloomerp/bloomerp"
    source_root = bloomerp_dir / args.type
    tests_root = bloomerp_dir / "tests" / args.type

    if not source_root.exists():
        print(f"Source type directory does not exist: {source_root}", file=sys.stderr)
        return 1

    base_class = TYPE_TO_BASE_CLASS[args.type]
    created = 0
    skipped = 0

    for source_file in iter_source_files(source_root):
        rel_source = source_file.relative_to(source_root)
        test_filename = f"test_{rel_source.stem}.py"
        test_path = tests_root / rel_source.parent / test_filename

        if test_path.exists():
            skipped += 1
            continue

        test_path.parent.mkdir(parents=True, exist_ok=True)
        content = build_test_content(base_class, rel_source)
        test_path.write_text(content, encoding="utf-8")
        created += 1

    print(f"Scaffold complete for type={args.type}: created={created}, skipped_existing={skipped}")
    return 0


raise SystemExit(main(sys.argv[2:]))
PY
}

case "${1:-}" in
    update-internal-sdk)
        shift
        update-internal-sdk "$@"
        ;;
    sync-cli-config-settings)
        shift
        sync-cli-config-settings "$@"
        ;;
  reset-test-data)
    shift
    reset-test-data "$@"
    ;;
  document-cotton-components)
    shift
    document-cotton-components "$@"
    ;;
    autoCreateTests)
        shift
        autoCreateTests "$@"
        ;;
  ""|-h|--help|help)
        echo "Usage: ./scripts.sh <command>"
        echo
        echo "Commands:"
        echo "  update-internal-sdk [create_sdk options]"
        echo "  sync-cli-config-settings [--check] [--no-backup]"
        echo "  reset-test-data"
        echo "  document-cotton-components"
                echo "  autoCreateTests --type [components|models|views|widgets]"
    ;;
  *)
    echo "Unknown command: $1" >&2
    echo "Usage: ./scripts.sh <command>" >&2
                                echo "Commands: update-internal-sdk, sync-cli-config-settings, reset-test-data, document-cotton-components, autoCreateTests" >&2
    exit 1
    ;;
esac
