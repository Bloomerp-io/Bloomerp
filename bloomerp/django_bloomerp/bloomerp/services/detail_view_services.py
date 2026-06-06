from bloomerp.models.base_bloomerp_model import FieldLayout, LayoutItem, LayoutRow
from bloomerp.models import ApplicationField
from django.db.models import Model
from bloomerp.models import AbstractBloomerpUser
from django.contrib.contenttypes.models import ContentType
from bloomerp.field_types import FieldType
from django.utils.translation import gettext_lazy as _
from bloomerp.models.users.user_detail_view_preference import UserDetailViewPreference
from bloomerp.router import router
from bloomerp.services.sectioned_layout_services import create_default_layout


# Default Folder Policy
# Update these constants/helpers to change default folder behavior globally.
DEFAULT_FOREIGN_FOLDER_ID = "foreign_relationships"
DEFAULT_FOREIGN_FOLDER_NAME = "Relationships"


def get_default_folder_definitions() -> list[dict]:
    """Returns the default folder behavior in one central place.

    This is intentionally centralized so default folder creation behavior is
    easy to find and modify.
    """
    return [
        {
            "id": DEFAULT_FOREIGN_FOLDER_ID,
            "name": DEFAULT_FOREIGN_FOLDER_NAME,
        }
    ]


def _is_foreign_relationship_tab(tab: dict) -> bool:
    url = tab.get("url")
    if not isinstance(url, str):
        return False
    return url.endswith("_relationship")


def _is_overview_tab(tab: dict) -> bool:
    url = tab.get("url")
    return isinstance(url, str) and url.endswith("_detail_overview")


def _is_files_tab(tab: dict) -> bool:
    url = tab.get("url")
    return isinstance(url, str) and url.endswith("_detail_files")


def _is_comments_tab(tab: dict) -> bool:
    url = tab.get("url")
    return isinstance(url, str) and url.endswith("_detail_comments")


def _is_delete_tab(tab: dict) -> bool:
    url = tab.get("url")
    return isinstance(url, str) and url.endswith("_detail_delete")


def _get_default_tab_priority(tab: dict) -> int:
    if _is_overview_tab(tab):
        return 0
    if _is_files_tab(tab):
        return 1
    if _is_comments_tab(tab):
        return 2
    if _is_foreign_relationship_tab(tab):
        return 4
    if _is_delete_tab(tab):
        return 5
    return 3


def get_default_tab_state() -> dict:
    return {
        "top_level_order": [],
        "folders": [],
        "active": None,
    }


def _normalize_tab_key_list(values: list | None) -> list[str]:
    if not isinstance(values, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _build_default_tab_state_from_resolved_keys(
    default_ordered_keys: list[str],
    foreign_keys: set[str],
) -> dict:
    top_level_order = [key for key in default_ordered_keys if key not in foreign_keys]
    folders: list[dict] = []

    if foreign_keys:
        relationship_order = [key for key in default_ordered_keys if key in foreign_keys]
        folders.append(
            {
                "id": DEFAULT_FOREIGN_FOLDER_ID,
                "name": DEFAULT_FOREIGN_FOLDER_NAME,
                "tab_order": relationship_order,
            }
        )

    return {
        "top_level_order": top_level_order,
        "folders": folders,
        "active": top_level_order[0] if top_level_order else (default_ordered_keys[0] if default_ordered_keys else None),
    }


def build_default_tab_state_from_tabs(tabs: list[dict]) -> dict:
    tabs = tabs or []
    available_by_key = {
        str(tab.get("key") or tab.get("url")): tab
        for tab in tabs
        if tab.get("key") or tab.get("url")
    }
    available_keys = list(available_by_key.keys())
    default_ordered_keys = sorted(
        available_keys,
        key=lambda key: (_get_default_tab_priority(available_by_key[key]), available_keys.index(key)),
    )
    foreign_keys = {
        key for key, tab in available_by_key.items() if _is_foreign_relationship_tab(tab)
    }
    return _build_default_tab_state_from_resolved_keys(default_ordered_keys, foreign_keys)


def _normalize_folders(values: list | None) -> list[dict]:
    if not isinstance(values, list):
        return []

    normalized: list[dict] = []
    seen_ids: set[str] = set()

    for value in values:
        if not isinstance(value, dict):
            continue

        folder_id = value.get("id")
        if not isinstance(folder_id, str) or not folder_id:
            continue
        if folder_id in seen_ids:
            continue

        name = value.get("name")
        if not isinstance(name, str) or not name.strip():
            name = folder_id.replace("_", " ").strip().title()

        tab_order = _normalize_tab_key_list(value.get("tab_order"))

        normalized.append(
            {
                "id": folder_id,
                "name": name.strip(),
                "tab_order": tab_order,
            }
        )
        seen_ids.add(folder_id)

    return normalized


def normalize_detail_tab_state(state: dict | None) -> dict:
    if not isinstance(state, dict):
        raise ValueError("Invalid tab state")

    top_level_order = state.get("top_level_order")
    folders = state.get("folders")
    active = state.get("active")
    if top_level_order is None or folders is None:
        raise ValueError("Invalid tab state")

    return {
        "top_level_order": _normalize_tab_key_list(top_level_order),
        "folders": _normalize_folders(folders),
        "active": active if isinstance(active, str) else None,
    }


def get_ordered_tab_keys_from_state(state: dict | None) -> list[str]:
    normalized_state = normalize_detail_tab_state(state)
    ordered_keys: list[str] = []

    for key in normalized_state["top_level_order"]:
        if key not in ordered_keys:
            ordered_keys.append(key)

    for folder in normalized_state["folders"]:
        for key in folder.get("tab_order", []):
            if key not in ordered_keys:
                ordered_keys.append(key)

    return ordered_keys


def resolve_tabs_with_state(tabs: list[dict], state: dict | None) -> tuple[dict, dict]:
    tabs = tabs or []
    available_by_key = {
        str(tab.get("key") or tab.get("url")): tab
        for tab in tabs
        if tab.get("key") or tab.get("url")
    }
    available_keys = list(available_by_key.keys())
    default_ordered_keys = sorted(
        available_keys,
        key=lambda key: (_get_default_tab_priority(available_by_key[key]), available_keys.index(key)),
    )
    default_state = build_default_tab_state_from_tabs(tabs)

    try:
        normalized_state_input = normalize_detail_tab_state(state)
    except ValueError:
        normalized_state_input = default_state

    folders = normalized_state_input["folders"]
    top_level_order = normalized_state_input["top_level_order"]
    active = normalized_state_input["active"]

    # Apply centralized default folder policy for foreign relationship tabs.
    foreign_keys = [key for key, tab in available_by_key.items() if _is_foreign_relationship_tab(tab)]
    foreign_keys_in_top_level = any(key in foreign_keys for key in top_level_order)
    foreign_keys_in_non_default_folders = any(
        key in foreign_keys
        for folder in folders
        if folder.get("id") != DEFAULT_FOREIGN_FOLDER_ID
        for key in folder.get("tab_order", [])
    )

    should_auto_create_default_foreign_folder = (
        bool(foreign_keys)
        and not foreign_keys_in_top_level
        and not foreign_keys_in_non_default_folders
    )

    if should_auto_create_default_foreign_folder:
        existing_folder_ids = {folder["id"] for folder in folders}
        for default_folder in get_default_folder_definitions():
            if default_folder["id"] not in existing_folder_ids:
                folders.append(
                    {
                        "id": default_folder["id"],
                        "name": default_folder["name"],
                        "tab_order": [],
                    }
                )

    folder_by_id = {folder["id"]: folder for folder in folders}

    # Deduplicate tab placements across top level + folders.
    placed_keys: set[str] = set()
    normalized_top: list[str] = []
    for key in top_level_order:
        if key not in available_by_key or key in placed_keys:
            continue
        normalized_top.append(key)
        placed_keys.add(key)

    for folder in folders:
        normalized_folder_tabs: list[str] = []
        for key in folder.get("tab_order", []):
            if key not in available_by_key or key in placed_keys:
                continue
            normalized_folder_tabs.append(key)
            placed_keys.add(key)
        folder["tab_order"] = normalized_folder_tabs

    # Assign unplaced tabs: foreign relationship tabs go to default folder, rest top-level.
    default_foreign_folder = folder_by_id.get(DEFAULT_FOREIGN_FOLDER_ID)
    for key in default_ordered_keys:
        if key in placed_keys:
            continue
        if default_foreign_folder is not None and key in foreign_keys:
            default_foreign_folder["tab_order"].append(key)
        else:
            normalized_top.append(key)
        placed_keys.add(key)

    if active not in available_by_key:
        active = normalized_top[0] if normalized_top else (default_ordered_keys[0] if default_ordered_keys else None)

    top_level_tabs: list[dict] = []
    for key in normalized_top:
        tab = dict(available_by_key[key])
        tab["key"] = key
        tab["is_active"] = key == active
        tab["is_delete"] = _is_delete_tab(tab)
        top_level_tabs.append(tab)

    rendered_folders: list[dict] = []
    for folder in folders:
        folder_tabs: list[dict] = []
        for key in folder.get("tab_order", []):
            if key not in available_by_key:
                continue
            tab = dict(available_by_key[key])
            tab["key"] = key
            tab["is_active"] = key == active
            tab["is_delete"] = _is_delete_tab(tab)
            folder_tabs.append(tab)

        rendered_folders.append(
            {
                "id": folder["id"],
                "name": folder["name"],
                "tabs": folder_tabs,
            }
        )

    normalized_state = {
        "top_level_order": normalized_top,
        "folders": [
            {
                "id": folder["id"],
                "name": folder["name"],
                "tab_order": folder.get("tab_order", []),
            }
            for folder in folders
        ],
        "active": active,
    }

    has_rendered_tabs = bool(top_level_tabs) or any(folder["tabs"] for folder in rendered_folders)
    if not has_rendered_tabs and available_keys:
        fallback_active = active if active in available_by_key else default_ordered_keys[0]
        active = fallback_active
        top_level_tabs = []
        for key in default_ordered_keys:
            tab = dict(available_by_key[key])
            tab["key"] = key
            tab["is_active"] = key == fallback_active
            tab["is_delete"] = _is_delete_tab(tab)
            top_level_tabs.append(tab)

        rendered_folders = []
        normalized_state = {
            "top_level_order": default_ordered_keys,
            "folders": [],
            "active": fallback_active,
        }

    rendered = {
        "top_level_tabs": top_level_tabs,
        "folders": rendered_folders,
        "active": active,
    }
    return rendered, normalized_state


def get_router_detail_tabs(model: type[Model]) -> list[dict]:
    tabs: list[dict] = []
    for route in router.filter(model=model, route_type="detail"):
        if route.nr_of_args() != 1:
            continue
        tabs.append(
            {
                "key": route.url_name,
                "name": route.name,
                "url": route.url_name,
                "path": route.path,
                "requires_pk": True,
            }
        )
    return tabs


def save_detail_tab_state(
    preference: UserDetailViewPreference,
    tabs: list[dict],
    state: dict,
) -> dict:
    _, normalized_state = resolve_tabs_with_state(tabs=tabs, state=state)
    preference.tab_state = normalized_state
    preference.save(update_fields=["tab_state"])
    return normalized_state


def get_default_layout(content_type:ContentType, user:AbstractBloomerpUser) -> FieldLayout:
    """Generates a default layout for a particular user

    Args:
        model (Model | AbstractBloomerpUser): the given model
        user (AbstractBloomerpUser): the user object

    Returns:
        FieldLayout: default sectioned layout
    """
    # 1. Get the fields
    fields = ApplicationField.objects.filter(
        content_type=content_type,
    )
    
    # TODO
    # 2. Check which fields the user has access to
    
    # Get the model
    model = content_type.model_class()
    if model:
        return create_default_layout(model)

    else:
        items = [
            LayoutItem(id=application_field.pk, colspan=1)
            for application_field in fields.exclude(field_type=FieldType.PROPERTY.value)
        ]
        return FieldLayout(
            rows=[
                LayoutRow(
                    title=str(_("Details")),
                    items=items,
                    columns=2
                )
            ]
        )
        
        
def create_default_detail_view_preference(content_type:ContentType, user:AbstractBloomerpUser) -> UserDetailViewPreference:
    """Creates a default detail view preference

    Args:
        content_type (ContentType): the content type
        user (AbstractBloomerpUser): the user

    Returns:
        UserDetailViewPreference: the detail view preference object
    """
    default_layout = get_default_layout(content_type, user)

    model = content_type.model_class()
    default_tabs = get_router_detail_tabs(model) if model else []

    return UserDetailViewPreference.objects.create(
        user=user,
        content_type=content_type,
        layout=default_layout.model_dump(),
        tab_state=build_default_tab_state_from_tabs(default_tabs),
    )
    
    

        
    
    
    
