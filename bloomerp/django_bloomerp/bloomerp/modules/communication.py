"""Communication accounts and their default management workspace."""

from bloomerp.models.definition import LayoutItem, LayoutRow, WorkspaceLayout
from bloomerp.workspaces.links_tile.model import Link, LinkTileConfig

from .definition import BloomerpModule


class CommunicationModule(BloomerpModule):
    """Group email, instant messaging, and inbox management."""

    id = "communication"
    code = "communication"
    name = "Communication"
    description = "Manage email accounts, instant messaging connections, and inboxes."
    icon = "fa-solid fa-comments"

    tiles = [
        LinkTileConfig(
            id="communication:email-accounts",
            name="Email accounts",
            description="Create and manage email accounts.",
            icon="fa-solid fa-envelope",
            links=[
                Link(name="Create an email account", url_name="email_accounts_add", is_internal=True),
                Link(name="View email accounts", url_name="email_accounts_model", is_internal=True),
            ],
        ),
        LinkTileConfig(
            id="communication:im-connections",
            name="IM connections",
            description="Create and manage instant messaging connections.",
            icon="fa-solid fa-comments",
            links=[
                Link(name="Create an IM connection", url_name="im_connections_add", is_internal=True),
                Link(name="View IM connections", url_name="im_connections_model", is_internal=True),
            ],
        ),
    ]

    workspaces = [
        WorkspaceLayout(
            name="Communication overview",
            is_default=True,
            rows=[
                LayoutRow(
                    title="Quick access",
                    columns=2,
                    items=[
                        LayoutItem(id="communication:email-accounts"),
                        LayoutItem(id="communication:im-connections"),
                    ],
                ),
            ],
        ),
    ]
