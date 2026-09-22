"""Synchronize defaults declared by Bloomerp models and modules."""

from typing import Any

from django.core.management.base import BaseCommand

from bloomerp.services.default_policy_services import sync_default_policies
from bloomerp.services.workspace_services import create_or_update_default_tiles


class Command(BaseCommand):
    help = "Create or update default tiles and model policies."

    def add_arguments(self, parser: Any) -> None:
        """Allow synchronization of all defaults or one domain."""
        parser.add_argument(
            "domain", nargs="?", choices=("tiles", "permissions"),
            help="Only synchronize the selected domain.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Synchronize the requested default domains and report their counts."""
        domain = options.get("domain")
        if domain in (None, "tiles"):
            tiles = create_or_update_default_tiles()
            self.stdout.write(f"Synchronized {len(tiles)} default tile(s).")
        if domain in (None, "permissions"):
            policies = sync_default_policies()
            self.stdout.write(f"Synchronized {len(policies)} default policy/policies.")
