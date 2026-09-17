from bloomerp.models.mixins.default_filters_mixin import DefaultFiltersMixin
from django.utils.translation import gettext_lazy as _
from typing import TYPE_CHECKING, Any

from django.contrib.contenttypes.models import ContentType
from django.db import models, transaction
from django.db.models import Q

from bloomerp.dataviews.definition import BaseDataView
from bloomerp.dataviews.calendar.config import CalendarDataView
from bloomerp.dataviews.card.config import CardDataView
from bloomerp.dataviews.gant.config import GanttDataView
from bloomerp.dataviews.kanban.config import KanbanDataView
from bloomerp.dataviews.pivot_table.config import PivotTableDataView
from bloomerp.dataviews.registry import DATAVIEW_REGISTRY, get_dataview_type_choices
from bloomerp.dataviews.table.config import TableDataView
from bloomerp.models.application_field import ApplicationField
from bloomerp.models.definition import get_model_config
from bloomerp.models.users.base_view_preference import BaseViewPreference
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager

if TYPE_CHECKING:
    from bloomerp.models.users.user import AbstractBloomerpUser

def get_default_display_fields() -> dict:
    """Returns the default display_fields structure for the UserListViewPreference model.

    Returns:
        dict: A dictionary with view types as keys and empty lists as values.
              Structure: {"table": [], "kanban": [], "calendar": []}
              Each list contains ApplicationField IDs in display order.
    """
    return {view_type.key: [] for view_type in DATAVIEW_REGISTRY.values()}


class UserListViewPreference(DefaultFiltersMixin, BaseViewPreference):
    """
    Model that stores the preferences of a user for list views for different content types.
    
    Key concepts:
    - Accessible fields: All fields the user has permission to see (based on field-level permissions).
                         These are shown in the display options UI for the user to toggle.
    - Visible fields: The subset of accessible fields that the user has chosen to display
                      for a specific view type. Stored in `display_fields` JSON.
    
    display_fields structure:
    {
        "table": [1, 5, 3],      # ApplicationField IDs in display order
        "kanban": [2, 4],
        "calendar": [1, 2]
    }
    """
    class Meta:
        verbose_name = _("User List View Preference")
        verbose_name_plural = _("User List View Preferences")
        db_table = 'bloomerp_user_list_view_pref'
        constraints = [
            models.UniqueConstraint(
                fields=["user", "content_type"],
                condition=Q(selected=True),
                name="unique_selected_list_view_preference",
            ),
            models.UniqueConstraint(
                fields=["user", "source_object"],
                condition=Q(source_object__isnull=False),
                name="unique_list_view_preference_reference",
            ),
        ]

    view_type = models.CharField(
        max_length=50,
        choices=get_dataview_type_choices,
        default=DATAVIEW_REGISTRY.get("table").key,
        verbose_name=_("View Type"),
    )
    split_view_enabled = models.BooleanField(default=False, verbose_name=_("Split View Enabled"))
    
    # Visible field IDs per view type (list of ApplicationField IDs in order)
    display_fields = models.JSONField(default=get_default_display_fields, verbose_name=_("Display Fields"))
    options : dict = models.JSONField(default=dict, verbose_name=_("Options"))
    
    def get_filter_scope(self) -> tuple[str, str]:
        return 'model', str(self.content_type_id)

    @classmethod
    def create_default_for_user(cls, user, **scope) -> "UserListViewPreference":
        """Create the user's default list-view preference for a content type.

        Expected scope: ``content_type_id``.
        """
        content_type = ContentType.objects.get(pk=scope["content_type_id"])
        model = content_type.model_class()
        config = get_model_config(model) if model is not None else None
        default_dataviews = (
            config.model_view_settings.default_dataviews
            if config is not None and config.model_view_settings is not None
            else []
        )

        if default_dataviews:
            return cls._create_configured_defaults(
                user=user,
                content_type=content_type,
                default_dataviews=default_dataviews,
            )

        return cls.objects.create(
            user=user,
            content_type=content_type,
        )

    @classmethod
    def _create_configured_defaults(
        cls,
        *,
        user: "AbstractBloomerpUser",
        content_type: ContentType,
        default_dataviews: list[BaseDataView],
    ) -> "UserListViewPreference":
        """Materialize all configured data views and return the selected one."""

        model = content_type.model_class()
        application_fields = list(
            ApplicationField.objects.filter(content_type=content_type)
        )
        fields_by_name = {
            application_field.field: application_field
            for application_field in application_fields
        }
        accessible_field_ids = set(
            UserPolicyManager(user).get_accessible_fields(
                content_type,
                BloomerpPermission.VIEW,
            ).values_list("id", flat=True)
        )

        selected_preference: UserListViewPreference | None = None
        with transaction.atomic():
            for data_view in default_dataviews:
                display_fields = get_default_display_fields()
                display_fields[data_view.view_type] = cls._resolve_field_ids(
                    data_view.display_fields,
                    fields_by_name=fields_by_name,
                    accessible_field_ids=accessible_field_ids,
                )
                options = {
                    data_view.view_type: cls._resolve_data_view_options(
                        data_view,
                        fields_by_name=fields_by_name,
                        accessible_field_ids=accessible_field_ids,
                    )
                }
                default_filters = cls._resolve_default_filters(
                    data_view.default_filters,
                    fields_by_name=fields_by_name,
                    accessible_field_ids=accessible_field_ids,
                )

                preference = cls.objects.create(
                    user=user,
                    content_type=content_type,
                    name=data_view.name,
                    selected=data_view.is_default,
                    view_type=data_view.view_type,
                    split_view_enabled=data_view.split_view_enabled,
                    display_fields=display_fields,
                    options=options,
                )
                if default_filters:
                    from bloomerp.filters.parser import parse_filters
                    from bloomerp.models.filters.filter import SavedFilter
                    saved = SavedFilter.objects.create(
                        name=f"{data_view.name} defaults {preference.pk}",
                        scope="model", identifier=str(content_type.pk),
                        filters=[group.model_dump(mode="json") for group in parse_filters(default_filters, model=content_type.model_class())],
                    )
                    preference.add_default_filter(saved)
                if data_view.is_default:
                    selected_preference = preference

        if selected_preference is None:
            raise ValueError("Configured data views must define one default.")
        return selected_preference

    @staticmethod
    def _resolve_field(
        field_name: str | None,
        *,
        fields_by_name: dict[str, ApplicationField],
        accessible_field_ids: set[int],
    ) -> ApplicationField | None:
        """Resolve a declared field name without granting inaccessible fields."""
        if field_name is None:
            return None

        normalized_name = field_name.strip()
        application_field = fields_by_name.get(normalized_name)
        if application_field is None:
            raise ValueError(f"Unknown data view field '{normalized_name}'.")
        if application_field.id not in accessible_field_ids:
            return None
        return application_field

    @classmethod
    def _resolve_field_ids(
        cls,
        field_names: list[str],
        *,
        fields_by_name: dict[str, ApplicationField],
        accessible_field_ids: set[int],
    ) -> list[int]:
        """Resolve declared field names to accessible ApplicationField IDs."""
        resolved_ids: list[int] = []
        for field_name in field_names:
            application_field = cls._resolve_field(
                field_name,
                fields_by_name=fields_by_name,
                accessible_field_ids=accessible_field_ids,
            )
            if application_field is not None:
                resolved_ids.append(application_field.id)
        return resolved_ids

    @classmethod
    def _resolve_data_view_options(
        cls,
        data_view: BaseDataView,
        *,
        fields_by_name: dict[str, ApplicationField],
        accessible_field_ids: set[int],
    ) -> dict[str, Any]:
        """Translate developer-facing field names to persisted view options."""
        def field_id(field_name: str | None) -> int | None:
            application_field = cls._resolve_field(
                field_name,
                fields_by_name=fields_by_name,
                accessible_field_ids=accessible_field_ids,
            )
            return application_field.id if application_field is not None else None

        def field_name(field: str | None) -> str | None:
            application_field = cls._resolve_field(
                field,
                fields_by_name=fields_by_name,
                accessible_field_ids=accessible_field_ids,
            )
            return application_field.field if application_field is not None else None

        if isinstance(data_view, TableDataView):
            return {
                "page_size": data_view.page_size,
                "sort_field": field_name(data_view.sort_field),
                "sort_direction": data_view.sort_direction,
            }
        if isinstance(data_view, KanbanDataView):
            return {
                "group_by_field_id": field_id(data_view.group_by_field),
                "page_size": data_view.page_size,
                "sort_field": field_name(data_view.sort_field),
                "sort_direction": data_view.sort_direction,
            }
        if isinstance(data_view, CardDataView):
            return {"page_size": data_view.page_size}
        if isinstance(data_view, CalendarDataView):
            return {
                "start_field_id": field_id(data_view.start_field),
                "end_field_id": field_id(data_view.end_field),
                "view_mode": data_view.view_mode,
                "color_grouping_field_id": field_id(
                    data_view.color_grouping_field
                ),
            }
        if isinstance(data_view, GanttDataView):
            return {
                "start_field_id": field_id(data_view.start_field),
                "end_field_id": field_id(data_view.end_field),
                "dependency_from_field_id": field_id(
                    data_view.dependency_from_field
                ),
                "dependency_for_field_id": field_id(
                    data_view.dependency_for_field
                ),
                "page_size": data_view.page_size,
            }
        if isinstance(data_view, PivotTableDataView):
            return {
                "row_field_ids": cls._resolve_field_ids(
                    data_view.row_fields,
                    fields_by_name=fields_by_name,
                    accessible_field_ids=accessible_field_ids,
                ),
                "column_field_ids": cls._resolve_field_ids(
                    data_view.column_fields,
                    fields_by_name=fields_by_name,
                    accessible_field_ids=accessible_field_ids,
                ),
                "value_field_ids": cls._resolve_field_ids(
                    data_view.value_fields,
                    fields_by_name=fields_by_name,
                    accessible_field_ids=accessible_field_ids,
                ),
                "aggregation": data_view.aggregation,
                "show_row_totals": data_view.show_row_totals,
                "show_column_totals": data_view.show_column_totals,
                "totals_scope": data_view.totals_scope,
                "page_size": data_view.page_size,
            }
        raise ValueError(f"Unsupported default data view '{data_view.view_type}'.")

    @classmethod
    def _resolve_default_filters(
        cls,
        default_filters: dict[str, str | list[str]],
        *,
        fields_by_name: dict[str, ApplicationField],
        accessible_field_ids: set[int],
    ) -> dict[str, str | list[str]]:
        """Keep configured filters only when their root field is accessible."""
        resolved_filters: dict[str, str | list[str]] = {}
        for filter_key, value in default_filters.items():
            root_field_name = filter_key.split("__", 1)[0]
            application_field = cls._resolve_field(
                root_field_name,
                fields_by_name=fields_by_name,
                accessible_field_ids=accessible_field_ids,
            )
            if application_field is not None:
                resolved_filters[filter_key] = value
        return resolved_filters

    @classmethod
    @transaction.atomic
    def copy_preference_for_user(
        cls,
        *,
        user,
        source: "UserListViewPreference",
        name: str,
        scope: dict | None = None,
    ) -> "UserListViewPreference":
        """Copy a list-view preference and its serialized options."""
        preference = cls._create_preference_copy(
            user=user,
            source=source,
            name=name,
            scope=scope,
        )
        source.copy_default_filters_to(preference)
        return preference

    def get_visible_field_ids(self, view_type: str = None) -> list[int]:
        """Returns the list of ApplicationField IDs that are visible for the given view type.

        Args:
            view_type: The view type to get fields for. Defaults to current view_type.
        Returns:
            list[int]: List of ApplicationField IDs in display order.
        """
        view_type = view_type or self.view_type
        return self.display_fields.get(view_type, [])
    
    def set_visible_field_ids(self, view_type: str, field_ids: list[int]) -> None:
        """Sets the visible field IDs for a specific view type.

        Args:
            view_type: The view type to set fields for.
            field_ids: List of ApplicationField IDs in display order.
        """
        if self.display_fields is None:
            self.display_fields = get_default_display_fields()
        self.display_fields[view_type] = field_ids
    
    def toggle_field(self, view_type: str, field_id: int) -> bool:
        """Toggles a field's visibility for a specific view type.

        Args:
            view_type: The view type to toggle the field for.
            field_id: The ApplicationField ID to toggle.
        Returns:
            bool: True if field is now visible, False if hidden.
        """
        if self.display_fields is None:
            self.display_fields = get_default_display_fields()
        
        current_fields = self.display_fields.get(view_type, [])
        
        if field_id in current_fields:
            current_fields.remove(field_id)
            is_visible = False
        else:
            current_fields.append(field_id)
            is_visible = True
        
        self.display_fields[view_type] = current_fields
        return is_visible
    
    @property
    def should_display_field_options(self) -> bool:
        """Determines if field visibility options should be displayed for the current view type.

        Returns:
            bool: True if field visibility options should be shown, False otherwise.
        """
        view_type_def = DATAVIEW_REGISTRY.get(self.view_type)
        return view_type_def.requires_display_fields
    
    
