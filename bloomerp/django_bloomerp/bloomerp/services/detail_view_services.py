from bloomerp.models.base_bloomerp_model import FieldLayout
from bloomerp.models import ApplicationField
from bloomerp.models.base_bloomerp_model import LayoutSection
from django.db.models import Model
from bloomerp.models import AbstractBloomerpUser
from django.contrib.contenttypes.models import ContentType
from bloomerp.field_types import FieldType
from django.utils.translation import gettext_lazy as _
from bloomerp.models import UserDetailViewPreference
from bloomerp.router import router


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


def _get_default_tab_state_v2() -> dict:
    return {
        "version": 2,
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


def build_default_tab_state_from_tabs(tabs: list[dict]) -> dict:
    _, normalized = resolve_tabs_with_state(tabs=tabs, state=_get_default_tab_state_v2())
    return normalized


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


def _convert_state_to_v2(state: dict | None) -> dict:
    state = state if isinstance(state, dict) else {}

    if state.get("version") == 2:
        return {
            "version": 2,
            "top_level_order": _normalize_tab_key_list(state.get("top_level_order")),
            "folders": _normalize_folders(state.get("folders")),
            "active": state.get("active") if isinstance(state.get("active"), str) else None,
        }

    # Backward compatibility with v1 state shape
    order = _normalize_tab_key_list(state.get("order"))
    active = state.get("active") if isinstance(state.get("active"), str) else None
    return {
        "version": 2,
        "top_level_order": order,
        "folders": [],
        "active": active,
    }


def resolve_tabs_with_state(tabs: list[dict], state: dict | None) -> tuple[dict, dict]:
    tabs = tabs or []
    available_by_key = {
        str(tab.get("key") or tab.get("url")): tab
        for tab in tabs
        if tab.get("key") or tab.get("url")
    }
    available_keys = list(available_by_key.keys())

    state_v2 = _convert_state_to_v2(state)
    folders = state_v2["folders"]
    top_level_order = state_v2["top_level_order"]
    active = state_v2["active"]

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
    for key in available_keys:
        if key in placed_keys:
            continue
        if default_foreign_folder is not None and key in foreign_keys:
            default_foreign_folder["tab_order"].append(key)
        else:
            normalized_top.append(key)
        placed_keys.add(key)

    if active not in available_by_key:
        active = normalized_top[0] if normalized_top else (available_keys[0] if available_keys else None)

    top_level_tabs: list[dict] = []
    for key in normalized_top:
        tab = dict(available_by_key[key])
        tab["key"] = key
        tab["is_active"] = key == active
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
            folder_tabs.append(tab)

        rendered_folders.append(
            {
                "id": folder["id"],
                "name": folder["name"],
                "tabs": folder_tabs,
            }
        )

    normalized_state = {
        "version": 2,
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
        fallback_active = active if active in available_by_key else available_keys[0]
        top_level_tabs = []
        for key in available_keys:
            tab = dict(available_by_key[key])
            tab["key"] = key
            tab["is_active"] = key == fallback_active
            top_level_tabs.append(tab)

        rendered_folders = []
        normalized_state = {
            "version": 2,
            "top_level_order": available_keys,
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
        list[LayoutSection]: list of layouts
    """
    # 1. Get the fields
    fields = ApplicationField.objects.filter(
        content_type=content_type,
    )
    
    # TODO
    # 2. Check which fields the user has access to
    
    # Get the model
    model = content_type.model_class()
    layout_sections = []
    if hasattr(model, "field_layout") and model.field_layout:
        field_layout = model.field_layout

        # Keep items as field identifier strings (not PKs)
        for section in field_layout.sections:
            items = [field_str for field_str in section.items]

            layout_sections.append(
                LayoutSection(
                    columns=section.columns,
                    title=section.title,
                    items=items
                )
            )

        return FieldLayout(sections=layout_sections)

    else:
        # Auto generate the layout using field identifiers (strings)
        items = list(fields.exclude(field_type=FieldType.PROPERTY.value).values_list("field", flat=True))
        return FieldLayout(
            sections=[
                LayoutSection(
                    title=_("Details"),
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
    # Get the FieldLayout with field identifier strings
    default_layout = get_default_layout(content_type, user)

    # Convert field identifier strings to ApplicationField PKs for storage
    stored_sections = []
    for section in default_layout.sections:
        items_pks = []
        for field_str in section.items:
            af = ApplicationField.objects.filter(content_type=content_type, field=field_str).first()
            if af:
                items_pks.append(af.pk)

        stored_sections.append({
            "title": section.title,
            "columns": section.columns,
            "items": items_pks,
        })

    model = content_type.model_class()
    default_tabs = get_router_detail_tabs(model) if model else []

    # Persist the converted layout
    return UserDetailViewPreference.objects.create(
        user=user,
        content_type=content_type,
        field_layout={"sections": stored_sections},
        tab_state=build_default_tab_state_from_tabs(default_tabs),
    )
    
        
    
    
    

