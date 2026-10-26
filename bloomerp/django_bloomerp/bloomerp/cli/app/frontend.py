"""Add an optional TypeScript workspace to an existing app."""

import click

from ..frontend import create_frontend
from ._utils import resolve_app_dir


@click.command("frontend")
@click.argument("name", required=False)
def frontend(name: str | None) -> None:
    """Create the frontend workspace for an existing app."""
    app_dir = resolve_app_dir(name)
    create_frontend(app_dir)
    click.echo(f"Created frontend at {app_dir / 'frontend'}")
