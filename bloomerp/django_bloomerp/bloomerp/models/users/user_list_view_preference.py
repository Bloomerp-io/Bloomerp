from django.db import models
from django.contrib.contenttypes.models import ContentType
from django.conf import settings
from bloomerp.models.application_field import ApplicationField
from django.db.models import Case, When


class ViewType(models.TextChoices):
    TABLE = 'table', 'Table'
    KANBAN = 'kanban', 'Kanban'
    CALENDAR = 'calendar', 'Calendar'
    GANT = 'gant', 'Gant'
    PIVOT_TABLE = 'pivot_table', 'Pivot'

    @property
    def icon(self):
        icons = {
            'table': 'list',
            'kanban': 'kanban',
            'calendar': 'calendar',
            'gant' : 'gant',
            'pivot_table' : 'pivot_table',
        }
        return icons.get(self.value, 'list')


class PageType(models.TextChoices):
    PAGINATION = 'pagination', 'Pagination'
    INFINITE_SCROLL = 'infinite_scroll', 'Infinite Scroll'


class PageSize(models.IntegerChoices):
    SIZE_10 = 10, '10'
    SIZE_25 = 25, '25'
    SIZE_50 = 50, '50'
    SIZE_100 = 100, '100'


class CalendarViewMode(models.TextChoices):
    DAY = 'day', 'Day'
    WEEK = 'week', 'Week'
    MONTH = 'month', 'Month'


def get_default_display_fields() -> dict:
    """Returns the default display_fields structure for the UserListViewPreference model.

    Returns:
        dict: A dictionary with view types as keys and empty lists as values.
              Structure: {"table": [], "kanban": [], "calendar": []}
              Each list contains ApplicationField IDs in display order.
    """
    return {view_type.value: [] for view_type in ViewType}


class UserListViewPreference(models.Model):
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
        unique_together = ('user', 'content_type')
        db_table = 'bloomerp_user_list_view_pref'
    
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='list_view_preferences'
    )
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    
    # View preferences
    page_size = models.PositiveIntegerField(choices=PageSize.choices, default=PageSize.SIZE_25)
    page_type = models.CharField(max_length=20, choices=PageType.choices, default=PageType.PAGINATION)
    view_type = models.CharField(max_length=50, choices=ViewType.choices, default=ViewType.TABLE)
    split_view_enabled = models.BooleanField(default=False)
    
    # Kanban preferences
    kanban_group_by_field = models.ForeignKey(
        to=ApplicationField, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='kanban_preferences'
    )
    
    # Calendar preferences
    calendar_start_field = models.ForeignKey(
        to=ApplicationField, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='calendar_start_preferences',
        help_text='Start date field for calendar events.'
    )
    calendar_end_field = models.ForeignKey(
        to=ApplicationField, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='calendar_end_preferences',
        help_text='Optional end date field for calendar events.'
    )
    calendar_view_mode = models.CharField(
        max_length=20, 
        choices=CalendarViewMode.choices, 
        default=CalendarViewMode.WEEK
    )
    
    # Visible field IDs per view type (list of ApplicationField IDs in order)
    display_fields = models.JSONField(default=get_default_display_fields)
    
    def __str__(self):
        return f"ListViewPreference for {self.user} on {self.content_type}"
    
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
    
    def is_field_visible(self, view_type: str, field_id: int) -> bool:
        """Checks if a field is visible for a specific view type.

        Args:
            view_type: The view type to check.
            field_id: The ApplicationField ID to check.
        Returns:
            bool: True if the field is visible.
        """
        return field_id in self.display_fields.get(view_type, [])
    
    def get_visible_fields_queryset(self, view_type: str = None) -> models.QuerySet:
        """Returns an ordered QuerySet of visible ApplicationFields.

        Args:
            view_type: The view type to get fields for. Defaults to current view_type.
        Returns:
            QuerySet[ApplicationField]: Ordered queryset of visible fields.
        """
        view_type = view_type or self.view_type
        field_ids = self.get_visible_field_ids(view_type)
        
        if not field_ids:
            return ApplicationField.objects.none()
        
        # Preserve ordering using CASE/WHEN
        ordering = Case(*[When(pk=pk, then=pos) for pos, pk in enumerate(field_ids)])
        return ApplicationField.objects.filter(pk__in=field_ids).order_by(ordering)
    
    
OPTIONS = {
    ViewType.TABLE: {
        ""
    },
    
    ViewType.CALENDAR : {
        "time_range" : {
            "type" : "select",
            "values" : ["day", "week", "year", "month"]
        },
    },
    
}

