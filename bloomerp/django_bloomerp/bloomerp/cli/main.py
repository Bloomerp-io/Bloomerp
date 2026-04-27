from __future__ import annotations

import keyword
import re
from pathlib import Path

import click


TEMPLATE_DIR = Path(__file__).resolve().parent / "template_project"


def _slugify_package_name(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_").lower()
    if not slug:
        raise click.ClickException("Project names must contain at least one letter or number.")
    if slug[0].isdigit():
        slug = f"project_{slug}"
    if keyword.iskeyword(slug):
        slug = f"{slug}_project"
    return slug


def _distribution_name(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9-]+", "-", value).strip("-").lower()
    if not slug:
        raise click.ClickException("Project names must contain at least one letter or number.")
    return slug


def _render_template(text: str, replacements: dict[str, str]) -> str:
    for placeholder, value in replacements.items():
        text = text.replace(placeholder, value)
    return text


def _copy_template_project(target_dir: Path, replacements: dict[str, str]) -> None:
    for source_path in sorted(TEMPLATE_DIR.rglob("*")):
        if "__pycache__" in source_path.parts or source_path.suffix == ".pyc":
            continue
        relative_path = source_path.relative_to(TEMPLATE_DIR)
        rendered_relative_path = Path(
            _render_template(relative_path.as_posix(), replacements)
        )
        destination_path = target_dir / rendered_relative_path

        if source_path.is_dir():
            destination_path.mkdir(parents=True, exist_ok=True)
            continue

        destination_path.parent.mkdir(parents=True, exist_ok=True)
        contents = source_path.read_text(encoding="utf-8")
        destination_path.write_text(
            _render_template(contents, replacements),
            encoding="utf-8",
        )


@click.group()
def main() -> None:
    """Bloomerp command line tools."""


@main.command()
@click.argument("directory", required=False)
def init(directory: str | None) -> None:
    """Create a minimal Django project configured for Bloomerp."""

    target_name = directory or click.prompt("Project directory", default="my-bloomerp-project")
    target_dir = Path(target_name).expanduser().resolve()

    default_project_name = target_dir.name
    project_name = click.prompt("Project name", default=default_project_name)
    app_name = click.prompt("Main Django app", default="core", show_default=True)
    app_name = _slugify_package_name(app_name)

    if target_dir.exists() and any(target_dir.iterdir()):
        raise click.ClickException(f"Target directory already exists and is not empty: {target_dir}")

    replacements = {
        "__PROJECT_NAME__": project_name,
        "__APP_NAME__": app_name,
        "__APP_CLASS_NAME__": "".join(part.capitalize() for part in app_name.split("_")) + "Config",
        "__DISTRIBUTION_NAME__": _distribution_name(project_name),
        "<app-name>": app_name,
    }

    _copy_template_project(target_dir, replacements)

    click.echo(f"Created Bloomerp project at {target_dir}")
    click.echo("")
    click.echo("Next steps:")
    click.echo(f"  cd {target_dir}")
    click.echo("  python -m venv .venv")
    click.echo("  source .venv/bin/activate")
    click.echo("  pip install -e .")
    click.echo("  python manage.py migrate")
    click.echo("  python manage.py createsuperuser")
    click.echo("  python manage.py save_application_fields")
    click.echo("  python manage.py runserver")


if __name__ == "__main__":
    main()
