"""Add an optional TypeScript workspace to an existing app."""

import click

from ..frontend import create_frontend, sync_frontend_api
from ._utils import resolve_app_dir


@click.command("frontend")
@click.argument("name", required=False)
@click.option(
    "--sync-api",
    is_flag=True,
    help="Refresh only the bundled API after checkout or a framework upgrade.",
)
def frontend(name: str | None, sync_api: bool) -> None:
    """Create an app frontend or refresh its generated local API dependency."""
    app_dir = resolve_app_dir(name)
    if sync_api:
        if not (app_dir / "frontend/package.json").is_file():
            raise click.ClickException(
                "This app has no frontend workspace. Run without --sync-api to create one."
            )
        sync_frontend_api(app_dir)
        click.echo(f"Refreshed bundled frontend API for {app_dir.name}")
        return
    create_frontend(app_dir)
    click.echo(f"Created frontend at {app_dir / 'frontend'}")
