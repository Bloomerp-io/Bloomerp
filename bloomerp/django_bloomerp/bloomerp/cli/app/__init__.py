from __future__ import annotations

import click

from .add_env import add_env
from .frontend import frontend
from .init import init
from .link import link
from .sync import sync
from .upload import upload


@click.group()
def app() -> None:
    """Create and publish reusable Bloomerp apps."""


app.add_command(init)
app.add_command(link)
app.add_command(sync)
app.add_command(add_env)
app.add_command(upload)
app.add_command(frontend)


__all__ = ["app"]
