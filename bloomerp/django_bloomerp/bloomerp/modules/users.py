from bloomerp.models.definition import LayoutItem, LayoutRow, WorkspaceLayout
from bloomerp.workspaces.links_tile.model import Link, LinkTileConfig

from .definition import BloomerpModule


class UsersModule(BloomerpModule):
    id = "users"
    code = "users"
    icon = "fa-solid fa-users"
    name = "Users & Permissions"
    description = "Manage users, roles, and permissions within the ERP system."

    tiles = [
        LinkTileConfig(
            id="users:user-management",
            name="User management",
            description="Manage user accounts and access.",
            icon="fa-solid fa-users",
            links=[
                Link(
                    name="View all users",
                    url_name="users_model",
                    is_internal=True,
                ),
                Link(
                    name="Create a user",
                    url_name="users_add",
                    is_internal=True,
                ),
            ],
        ),
        LinkTileConfig(
            id="users:permission-management",
            name="Permission management",
            description="Manage groups and access-control policies.",
            icon="fa-solid fa-user-shield",
            links=[
                Link(
                    name="View groups",
                    url_name="groups_model",
                    is_internal=True,
                ),
                Link(
                    name="Create a group",
                    url_name="groups_add",
                    is_internal=True,
                ),
                Link(
                    name="View access-control policies",
                    url_name="access_control_policies_model",
                    is_internal=True,
                ),
                Link(
                    name="Create a policy",
                    url_name="access_control_policies_add",
                    is_internal=True,
                ),
            ],
        ),
    ]

    workspaces = [
        WorkspaceLayout(
            name="Users & Permissions overview",
            is_default=True,
            rows=[
                LayoutRow(
                    title="Quick access",
                    columns=2,
                    items=[
                        LayoutItem(id="users:user-management"),
                        LayoutItem(id="users:permission-management"),
                    ],
                ),
            ],
        )
    ]
