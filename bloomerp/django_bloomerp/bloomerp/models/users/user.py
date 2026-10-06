from django.db import models
from django.contrib.auth.models import AbstractUser
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q, QuerySet
from django.contrib.auth.models import Permission
from django.utils.translation import gettext_lazy as _, gettext_noop
from bloomerp.models import BloomerpModel

from bloomerp.models.definition import BloomerpModelConfig, DetailViewSettings, FieldLayout, LayoutItem, LayoutRow
from bloomerp.models.mixins.absolute_url_model_mixin import AbsoluteUrlModelMixin
from bloomerp.models.mixins.avatar_model_mixin import AvatarModelMixin



USER_CONFIG = BloomerpModelConfig(
    module="users",
    detail_view_settings=DetailViewSettings(
        layouts=[FieldLayout(
            rows=[
                LayoutRow(
                    columns=2,
                    title=gettext_noop("Profile"),
                    items=[
                        LayoutItem(id="username"),
                        LayoutItem(id="email"),
                        LayoutItem(id="first_name"),
                        LayoutItem(id="last_name"),
                    ],
                ),
                LayoutRow(
                    columns=2,
                    title=gettext_noop("Access"),
                    items=[
                        LayoutItem(id="is_active"),
                        LayoutItem(id="is_staff"),
                        LayoutItem(id="is_superuser"),
                        LayoutItem(id="groups"),
                    ],
                ),
            ]
        )],
    ),
)


class DateViewPreference(models.TextChoices):
    DAY_MONTH_YEAR = "d-m-Y", _("Day-Month-Year (15-08-2000)")
    MONTH_DAY_YEAR = "m-d-Y", _("Month-Day-Year (08-15-2000)")
    YEAR_MONTH_DAY = "Y-m-d", _("Year-Month-Day (2000-08-15)")


class DatetimeViewPreference(models.TextChoices):
    DAY_MONTH_YEAR = (
        "d-m-Y H:i",
        _("Day-Month-Year Hour:Minute (15-08-2000 12:30)"),
    )
    MONTH_DAY_YEAR = (
        "m-d-Y H:i",
        _("Month-Day-Year Hour:Minute (08-15-2000 12:30)"),
    )
    YEAR_MONTH_DAY = (
        "Y-m-d H:i",
        _("Year-Month-Day Hour:Minute (2000-08-15 12:30)"),
    )


class DetailSidebarViewPreference(models.TextChoices):
    ACTIVITY = "activity", _("Activity")
    COMMENTS = "comments", _("Comments")


class AbstractBloomerpUser(
    AbstractUser, 
    AbsoluteUrlModelMixin,
    AvatarModelMixin
    ):
    class Meta:
        abstract = True
    
    default_email_account = models.ForeignKey(
        "bloomerp.EmailAccount",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="default_for_users",
        verbose_name=_("Default Email Account"),
        help_text=_("Preferred sender when composing outside an inbox."),
    )

    date_view_preference = models.CharField(
        max_length=20,
        default=DateViewPreference.DAY_MONTH_YEAR,
        choices=DateViewPreference.choices,
        help_text=_("The date format to be used in the application"),
        verbose_name=_("Date View Preference"),
    )

    datetime_view_preference = models.CharField(
        max_length=20,
        default=DatetimeViewPreference.DAY_MONTH_YEAR,
        choices=DatetimeViewPreference.choices,
        help_text=_("The datetime format to be used in the application"),
        verbose_name=_("Datetime View Preference"),
    )

    detail_sidebar_view_preference = models.CharField(
        max_length=20,
        default=DetailSidebarViewPreference.ACTIVITY,
        choices=DetailSidebarViewPreference.choices,
        help_text=_("The detail view sidebar panel to show first"),
        verbose_name=_("Detail Sidebar View Preference"),
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


class AbstractBloomerpEmailUser(AbstractBloomerpUser):
    email = models.EmailField(unique=True, verbose_name=_("Email"))

    class Meta:
        abstract = True

class User(AbstractBloomerpUser):
    bloomerp_config = USER_CONFIG

    class Meta(BloomerpModel.Meta):
        verbose_name = _("User")
        verbose_name_plural = _("Users")
        db_table = "auth_user"
        swappable = "AUTH_USER_MODEL"


