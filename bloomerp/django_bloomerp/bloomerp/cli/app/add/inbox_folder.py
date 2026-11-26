# Proposed scaffolding parameters for an inbox folder and its associated item type.
# app: str | None = None - Target app; resolve with cli.app._utils.resolve_app_dir.
# name: str - Python module name and generated symbol prefix.
# key: str - Symbolic INBOX_FOLDER_REGISTRY registration key.
# folder_key: str - Persisted InboxFolderTypeDefinition.key.
# label: str - Human-readable folder name.
# description: str | None = None - Explanation of the inbox category.
# icon: str | None = None - Folder icon.
# source_model: str | None = None - Django app_label.Model owning the folder.
# item_key: str | None = None - Associated InboxItemTypeDefinition.key, if any.
# item_label: str | None = None - Singular item name; derive its plural if omitted.
# item_source_model: str | None = None - Optional Django model backing inbox items.
# actions: tuple[str, ...] = () - Folder InboxActionDefinition import paths.
# item_actions: tuple[str, ...] = () - Item InboxActionDefinition import paths.
# filters: str | None = None - Filter definitions or filter-factory import path.
# default_sources: tuple[str, ...] = () - Inbox source definition import paths.
# is_default: bool = False - Whether this is a default folder type.
# is_aggregate: bool = False - Whether this folder combines other folders.
# hooks: tuple[str, ...] = () - Scaffold on_query, on_group, aggregate_func,
#   item on_render, item on_delete, and item on_mark_as_read callbacks.
# Registration: INBOX_FOLDER_REGISTRY.register(key, definition); item types are nested.
