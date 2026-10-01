"""
All rights reserved. 
"""
from dataclasses import dataclass

from django.contrib.contenttypes.models import ContentType

from bloomerp.field_types.registry import FIELD_TYPE_REGISTRY
from bloomerp.models.application_field import ApplicationField
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.services.preference_services import PreferenceManager

AUTO_MANAGED_FIELD_NAMES = {
    "id",
    "pk",
    "datetime_created",
    "datetime_updated",
    "created_by",
    "updated_by",
}

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

    @property
    def ordered_fields(self) -> list[tuple[ApplicationField, bool]]:
        """List displayed fields in their saved order, followed by other accessible fields."""
        visible_ids = {field.id for field in self.visible_fields}
        return [(field, True) for field in self.visible_fields] + [
            (field, False)
            for field, _is_visible in self.accessible_fields
            if field.id not in visible_ids
        ]


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


def get_data_view_fields(
    preference: UserListViewPreference,
    view_type: str | None = None,
    user: AbstractBloomerpUser | None = None,
) -> DataViewFields:
    """Gets the visible and accessible fields for a user's list view preference.
    
    Args:
        preference (UserListViewPreference): The user's list view preference.
        view_type (str): Optional view type override. Defaults to preference.view_type.
        user: User whose field permissions should be applied. Defaults to the
            preference owner for backward compatibility.
    Returns:
        DataViewFields: Container with visible_fields and accessible_fields.
    """
    view_type = view_type or preference.view_type
    permission_user = user or preference.user
    is_preference_owner = permission_user.pk == preference.user_id
    configured_visible_field_ids = preference.get_visible_field_ids(view_type)

    # Get all accessible fields for this user and content type
    manager = UserPolicyManager(permission_user)

    accessible_fields_qs = manager.get_accessible_fields(
        preference.content_type,
        BloomerpPermission.VIEW
    ).exclude(
        field_type__in=[
            FIELD_TYPE_REGISTRY.ONE_TO_MANY_FIELD.id,
        ]
    )
    
    if is_preference_owner:
        # Retain the existing self-healing behavior for an owner's preference.
        visible_field_ids = _sanitize_visible_field_ids(
            preference,
            accessible_fields_qs,
            view_type,
        )
    else:
        # Shared preferences are presentation state owned by somebody else.
        # Project them through the viewer's permissions without mutating them.
        accessible_field_ids = set(
            accessible_fields_qs.values_list("id", flat=True)
        )
        visible_field_ids = [
            field_id
            for field_id in configured_visible_field_ids
            if field_id in accessible_field_ids
        ]

    # If no visible fields are set, prefer business fields before audit/system fields.
    should_apply_defaults = not visible_field_ids and (
        is_preference_owner or not configured_visible_field_ids
    )
    if should_apply_defaults:
        preferred_fields = accessible_fields_qs.exclude(field__in=AUTO_MANAGED_FIELD_NAMES)
        default_fields = list(preferred_fields[:5].values_list('id', flat=True))
        if not default_fields:
            default_fields = list(accessible_fields_qs[:5].values_list('id', flat=True))
        visible_field_ids = default_fields
        if is_preference_owner:
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
    preference = PreferenceManager(user).get_or_create_selected(
        UserListViewPreference,
        scope={
            "content_type_id" : content_type.id
        }
    )
    view_type = view_type or preference.view_type

    manager = UserPolicyManager(user)
    accessible_field_ids = set(
        manager.get_accessible_fields(content_type, BloomerpPermission.VIEW).values_list("id", flat=True)
    )

    if field_id not in accessible_field_ids:
        return False, preference
    
    # Verify the field exists and is accessible
    is_visible = preference.toggle_field(view_type, field_id)
    preference.save(update_fields=['display_fields'])
    
    return is_visible, preference
