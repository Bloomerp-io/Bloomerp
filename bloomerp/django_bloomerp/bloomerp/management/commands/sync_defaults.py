"""Synchronize defaults declared by Bloomerp models and modules."""

from typing import Any

from django.core.management.base import BaseCommand

from bloomerp.docs_generator.tutorials.sync_tutorials import sync_default_tutorials
from bloomerp.permissions.default_policies import sync_default_policies
from bloomerp.services.workspace_services import create_or_update_default_tiles


class Command(BaseCommand):
    help = "Create or update default tutorials, tiles and model policies after migrations."

    def add_arguments(self, parser: Any) -> None:
        """Allow synchronization of all defaults or one domain."""
        parser.add_argument(
            "domain", nargs="?", choices=("tiles", "permissions", "tutorials"),
            help="Only synchronize the selected domain.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Synchronize the requested default domains and report their counts."""
        domain = options.get("domain")
        if domain in (None, "tutorials"):
            result = sync_default_tutorials()
            self.stdout.write(
                f"Synchronized {result.tutorials} default tutorial(s) and "
                f"{result.topics} topic(s). Retired {result.retired} tutorial(s)."
            )
        if domain in (None, "tiles"):
            tiles = create_or_update_default_tiles()
            self.stdout.write(f"Synchronized {len(tiles)} default tile(s).")
        if domain in (None, "permissions"):
            policies = sync_default_policies()
            self.stdout.write(f"Synchronized {len(policies)} default policy/policies.")
