from __future__ import annotations

import keyword
import re
from pathlib import Path

import click

from ..base import BloomerpAppDjango, BloomerpAppManifest
from ..toml import write_toml_model

APP_TEMPLATE_DIR = (
    Path(__file__).resolve().parent.parent / "template_project" / "<app-name>"
)


def normalize_app_name(value: str) -> str:
    app_name = re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_").lower()
    if not app_name:
        raise click.ClickException("App names must contain at least one letter or number.")
    if app_name[0].isdigit():
        app_name = f"app_{app_name}"
    if keyword.iskeyword(app_name):
        app_name = f"{app_name}_app"
    return app_name


def _render_template(text: str, replacements: dict[str, str]) -> str:
    for placeholder, value in replacements.items():
        text = text.replace(placeholder, value)
    return text


def _copy_app_template(target_dir: Path, replacements: dict[str, str]) -> None:
    for source_path in sorted(APP_TEMPLATE_DIR.rglob("*")):
        if "__pycache__" in source_path.parts or source_path.suffix == ".pyc":
            continue

        relative_path = source_path.relative_to(APP_TEMPLATE_DIR)
        destination_path = target_dir / relative_path
        if source_path.is_dir():
            destination_path.mkdir(parents=True, exist_ok=True)
            continue

        destination_path.parent.mkdir(parents=True, exist_ok=True)
        destination_path.write_text(
            _render_template(source_path.read_text(encoding="utf-8"), replacements),
            encoding="utf-8",
        )


def create_app(name: str, parent_dir: Path, *, frontend: bool = False) -> Path:
    """Create a reusable app, optionally including a TypeScript frontend workspace."""
    app_name = normalize_app_name(name)
    app_import_path = f"apps.{app_name}"
    apps_dir = parent_dir / "apps"
    target_dir = apps_dir / app_name
    if target_dir.exists() and any(target_dir.iterdir()):
        raise click.ClickException(
            f"Target app directory already exists and is not empty: {target_dir}"
        )

    apps_dir.mkdir(parents=True, exist_ok=True)
    (apps_dir / "__init__.py").touch(exist_ok=True)

    replacements = {
        "__APP_NAME__": app_import_path,
        "__APP_CLASS_NAME__": "".join(
            part.capitalize() for part in app_name.split("_")
        )
        + "Config",
    }
    _copy_app_template(target_dir, replacements)
    write_toml_model(
        target_dir / "app.bloomerp.toml",
        BloomerpAppManifest(name=app_name, django=BloomerpAppDjango(app_config=f"{app_import_path}.apps.{replacements['__APP_CLASS_NAME__']}")),
    )
    if frontend:
        from ..frontend import create_frontend

        create_frontend(target_dir)
    return target_dir


@click.command()
@click.argument("name")
@click.option("--frontend", is_flag=True, help="Include a TypeScript/Vite frontend workspace.")
def init(name: str, frontend: bool) -> None:
    """Create a reusable Django app package."""

    target_dir = create_app(name, Path.cwd(), frontend=frontend)
    click.echo(f"Created Bloomerp app at {target_dir}")
