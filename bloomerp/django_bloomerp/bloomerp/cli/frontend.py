"""Scaffold and build optional app-owned frontend bundles."""

import shutil
import subprocess
from importlib.metadata import version
from pathlib import Path

import click


def create_frontend(app_dir: Path) -> None:
    """Create a frontend workspace and discovery descriptor without overwriting files."""
    template_root = Path(__file__).parent / "template_frontend"
    replacements = {
        "__APP_LABEL__": app_dir.name,
        "__BLOOMERP_VERSION__": version("Bloomerp"),
    }
    targets: dict[Path, str] = {}
    for source in template_root.rglob("*"):
        if not source.is_file() or "__pycache__" in source.parts:
            continue
        relative = source.relative_to(template_root).as_posix()
        contents = source.read_text(encoding="utf-8")
        for placeholder, value in replacements.items():
            relative = relative.replace(placeholder, value)
            contents = contents.replace(placeholder, value)
        targets[app_dir / relative] = contents
    if (app_dir / "frontend").exists() or any(path.exists() for path in targets):
        raise click.ClickException(
            f"Frontend files already exist in {app_dir}; no files were changed."
        )
    for destination, contents in targets.items():
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(contents, encoding="utf-8")


def build_frontend(app_dir: Path) -> None:
    """Compile optional frontend assets before packaging an app wheel."""
    workspace = app_dir / "frontend"
    if not (workspace / "package.json").is_file():
        return
    npm = shutil.which("npm")
    if npm is None:
        raise click.ClickException(
            f"Node.js and npm are required to build the frontend in {workspace}."
        )
    install = "ci" if (workspace / "package-lock.json").is_file() else "install"
    try:
        subprocess.run([npm, install], cwd=workspace, check=True)
        subprocess.run([npm, "run", "build"], cwd=workspace, check=True)
    except (OSError, subprocess.CalledProcessError) as error:
        raise click.ClickException(
            f"Frontend build failed in {workspace}; app wheel was not built."
        ) from error
