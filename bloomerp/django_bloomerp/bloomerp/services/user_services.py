"""
All rights reserved. 
"""
from bloomerp.models.application_field import ApplicationField
from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from django.contrib.contenttypes.models import ContentType
from bloomerp.models.users.user import AbstractBloomerpUser
from django.core.cache import cache
from dataclasses import dataclass
from bloomerp.models import UserDetailViewPreference
from bloomerp.services.permission_services import UserPermissionManager, create_permission_str
from bloomerp.field_types import FieldType

@dataclass
class DataViewFields:
    """Container for visible and accessible fields in a data view.
    
    Attributes:
        visible_fields: List of ApplicationFields currently displayed for the view type.
        accessible_fields: List of tuples (ApplicationField, is_visible) for all fields 
                          the user can access. Used in display options UI.
    """
    visible_fields: list[ApplicationField]
    accessible_fields: list[tuple]


def _sanitize_visible_field_ids(
    preference: UserListViewPreference,
    accessible_fields_qs,
    view_type: str,
) -> list[int]:
    accessible_field_ids = list(accessible_fields_qs.values_list("id", flat=True))
    accessible_field_ids_set = set(accessible_field_ids)

    visible_field_ids = [
        field_id
        for field_id in preference.get_visible_field_ids(view_type)
        if field_id in accessible_field_ids_set
    ]

    if visible_field_ids != preference.get_visible_field_ids(view_type):
        preference.set_visible_field_ids(view_type, visible_field_ids)
        preference.save(update_fields=["display_fields"])

    return visible_field_ids


def get_data_view_fields(preference: UserListViewPreference, view_type: str = None) -> DataViewFields:
    """Gets the visible and accessible fields for a user's list view preference.
    
    Args:
        preference (UserListViewPreference): The user's list view preference.
        view_type (str): Optional view type override. Defaults to preference.view_type.
    Returns:
        DataViewFields: Container with visible_fields and accessible_fields.
    """
    view_type = view_type or preference.view_type
    
    # Get all accessible fields for this user and content type
    manager = UserPermissionManager(preference.user)
    permission_str = create_permission_str(preference.content_type.model_class(), "view")
    
    accessible_fields_qs = manager.get_accessible_fields(
        preference.content_type,
        permission_str
    ).exclude(
        field_type__in=[
            FieldType.ONE_TO_MANY_FIELD.value.id,
            FieldType.MANY_TO_MANY_FIELD.value.id
        ]
    )
    
    # Remove persisted fields the user can no longer access.
    visible_field_ids = _sanitize_visible_field_ids(preference, accessible_fields_qs, view_type)
    
    # If no visible fields are set, use default fields (first 5)
    if not visible_field_ids:
        default_fields = list(accessible_fields_qs[:5].values_list('id', flat=True))
        visible_field_ids = default_fields
        # Optionally persist the defaults
        preference.set_visible_field_ids(view_type, default_fields)
        preference.save(update_fields=['display_fields'])
    
    # Get visible fields in persisted display order, limited to accessible fields.
    accessible_fields_by_id = {field.id: field for field in accessible_fields_qs}
    visible_fields = [
        accessible_fields_by_id[field_id]
        for field_id in visible_field_ids
        if field_id in accessible_fields_by_id
    ]
    
    # Build accessible fields list with visibility flag
    visible_field_ids_set = set(visible_field_ids)
    accessible_fields = [
        (field, field.id in visible_field_ids_set)
        for field in accessible_fields_qs
    ]
    
    return DataViewFields(
        visible_fields=visible_fields,
        accessible_fields=accessible_fields
    )


def clear_user_list_view_preference_cache(user: AbstractBloomerpUser, content_type: ContentType) -> None:
    """Clears the cached list view preference for a user and content type.
    
    Call this function when:
    - User updates their field preferences
    - Admin modifies ApplicationField records
    - Model schema changes
    
    Args:
        user (AbstractBloomerpUser): The user whose cache to clear.
        content_type (ContentType): The content type to clear cache for.
    """
    cache_key = f'list_view_pref:{user.id}:{content_type.id}'
    cache.delete(cache_key)


def get_user_list_view_preference(user: AbstractBloomerpUser, content_type: ContentType) -> UserListViewPreference:
    """Gets the UserListViewPreference for a user and content type, creating a default if none exists.
    
    Args:
        user (AbstractBloomerpUser): The user for whom to get the preference.
        content_type (ContentType): The content type for which to get the preference.
    Returns:
        UserListViewPreference: The user's list view preference.
    """
    preference, _ = UserListViewPreference.objects.get_or_create(
        user=user,
        content_type=content_type
    )
    return preference


def toggle_field_visibility(
    user: AbstractBloomerpUser, 
    content_type: ContentType, 
    field_id: int, 
    view_type: str = None
) -> tuple[bool, UserListViewPreference]:
    """Toggles a field's visibility for a user's list view preference.
    
    Args:
        user: The user.
        content_type: The content type.
        field_id: The ApplicationField ID to toggle.
        view_type: Optional view type. Defaults to preference's current view_type.
    Returns:
        tuple: (is_now_visible, preference)
    """
    preference = get_user_list_view_preference(user, content_type)
    view_type = view_type or preference.view_type

    manager = UserPermissionManager(user)
    permission_str = create_permission_str(content_type.model_class(), "view")
    accessible_field_ids = set(
        manager.get_accessible_fields(content_type, permission_str).values_list("id", flat=True)
    )

    if field_id not in accessible_field_ids:
        return False, preference
    
    # Verify the field exists and is accessible
    is_visible = preference.toggle_field(view_type, field_id)
    preference.save(update_fields=['display_fields'])
    
    return is_visible, preference

