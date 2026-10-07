

from bloomerp.communication.definition import (
    InboxFolderTypeDefinition,
)
from bloomerp.communication.builtins.all.definition import ALL
from bloomerp.communication.builtins.emails.definition import EMAIL
from bloomerp.communication.builtins.in_app_notifications.definition import IN_APP_NOTIFICATIONS
from bloomerp.utils.registry import BaseRegistry


class InboxFolderRegistry(BaseRegistry[InboxFolderTypeDefinition]):
    def register(self, key: str, obj: InboxFolderTypeDefinition) -> None:
        if any(folder_type.key == obj.key for folder_type in self.values()):
            raise ValueError(f"Inbox folder key {obj.key!r} is already registered")
        super().register(key, obj)

    def get(self, key: str) -> InboxFolderTypeDefinition | None:
        registered = super().get(key)
        if registered is not None:
            return registered
        return next(
            (folder_type for folder_type in self.values() if folder_type.key == key),
            None,
        )

    def choices(self) -> list[tuple[str, str]]:
        return [(folder_type.key, folder_type.name) for folder_type in self.values()]

    def item_type_choices(self) -> list[tuple[str, str]]:
        return [
            (folder_type.item_type.key, folder_type.item_type.name)
            for folder_type in self.values()
            if folder_type.item_type is not None
        ]

    def get_item_type_by_key(self, key: str):
        for folder_type in self.values():
            if folder_type.item_type and folder_type.item_type.key == key:
                return folder_type.item_type
        raise ValueError(f"No matching inbox item type found for key: {key}")


INBOX_FOLDER_REGISTRY = InboxFolderRegistry(InboxFolderTypeDefinition)

INBOX_FOLDER_REGISTRY.register("ALL", ALL)
INBOX_FOLDER_REGISTRY.register(
    "IN_APP_NOTIFICATIONS",
    IN_APP_NOTIFICATIONS,
)
INBOX_FOLDER_REGISTRY.register("EMAIL", EMAIL)


def inbox_folder_choices() -> list[tuple[str, str]]:
    """Return folder choices lazily so extension registrations are included."""
    return INBOX_FOLDER_REGISTRY.choices()


def inbox_item_type_choices() -> list[tuple[str, str]]:
    """Return item choices lazily so extension registrations are included."""
    return INBOX_FOLDER_REGISTRY.item_type_choices()
