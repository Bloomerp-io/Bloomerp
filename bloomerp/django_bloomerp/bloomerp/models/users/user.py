from django.db import models
from django.contrib.auth.models import AbstractUser
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q, QuerySet
from django.contrib.auth.models import Permission
from django.utils.translation import gettext as _
from bloomerp.models.base_bloomerp_model import BloomerpModel
from bloomerp.models.mixins import (
    AbsoluteUrlModelMixin,
    AvatarModelMixin,
    StringSearchModelMixin,
)
from bloomerp.models.workspaces.sidebar_item import Sidebar


class AbstractBloomerpUser(
    AbstractUser, 
    StringSearchModelMixin, 
    AbsoluteUrlModelMixin,
    AvatarModelMixin
    ):
    class Meta:
        abstract = True

    # String search mixin fields
    string_search_fields = ['first_name+last_name', 'username']
    allow_string_search = True

    class Bloomerp:
        modules = ["users"]
    
    # ------------------------------------------------
    # User Preferences
    # ------------------------------------------------
    FILE_VIEW_PREFERENCE_CHOICES = [
        ("card", "Card View"),
        ("list", "List View"),
    ]

    DATE_VIEW_PREFERENCE_CHOICES = [
        ("d-m-Y", "Day-Month-Year (15-08-2000)"),
        ("m-d-Y", "Month-Day-Year (08-15-2000)"),
        ("Y-m-d", "Year-Month-Day (2000-08-15)"),
    ]

    DATETIME_VIEW_PREFERENCE_CHOICES = [
        ("d-m-Y H:i", "Day-Month-Year Hour:Minute (15-08-2000 12:30)"),
        ("m-d-Y H:i", "Month-Day-Year Hour:Minute (08-15-2000 12:30)"),
        ("Y-m-d H:i", "Year-Month-Day Hour:Minute (2000-08-15 12:30)"),
    ]

    file_view_preference = models.CharField(
        max_length=20, default="card", choices=FILE_VIEW_PREFERENCE_CHOICES
    )

    date_view_preference = models.CharField(
        max_length=20, default="d-m-Y", choices=DATE_VIEW_PREFERENCE_CHOICES, help_text=_("The date format to be used in the application")
    )

    datetime_view_preference = models.CharField(
        max_length=20, default="d-m-Y H:i", choices=DATETIME_VIEW_PREFERENCE_CHOICES, help_text=_("The datetime format to be used in the application")
    )

    
    def __str__(self):
        return self.username

    def get_content_types_for_user(self, permission_types:list[str]=["view"]) -> QuerySet[ContentType]:
        """
        Get all content types the user has permissions for based on the provided permission types.
        Permission types are the prefixes of the permission codenames, e.g. 'view', 'add', 'change', 'delete'.
        """
        if self.is_superuser:
            return ContentType.objects.all()

        # Build the query for filtering permissions based on the provided types
        permission_filters = Q()
        for perm_type in permission_types:
            permission_filters |= Q(codename__startswith=perm_type + "_")

        # Get all permissions for the user, including those via groups
        user_permissions = self.user_permissions.filter(
            permission_filters
        ) | Permission.objects.filter(permission_filters, group__user=self)

        # Get the content types for all permissions the user has
        content_types = ContentType.objects.filter(
            permission__in=user_permissions
        ).distinct()

        return content_types


    @property
    def accessible_content_types(self) -> QuerySet:
        '''
        Property that returns all content types the user has view access to.
        '''
        # TODO: Get rid of this property
        return self.get_content_types_for_user(permission_types=["view"])

    @property
    def selected_sidebar(self) -> Sidebar:
        """
        Returns the sidebar items for the user's selected sidebar, ordered by position.
        """
        selected_sidebar = self.sidebars.filter(selected=True).first()
        if selected_sidebar:
            return selected_sidebar

        first_sidebar = self.sidebars.order_by("id").first()
        if first_sidebar:
            first_sidebar.select()
            return first_sidebar

        return Sidebar.objects.create(
            user=self,
            selected=True,
        )
    
class User(AbstractBloomerpUser):
    class Meta(BloomerpModel.Meta):
        db_table = "auth_user"
        swappable = "AUTH_USER_MODEL"
