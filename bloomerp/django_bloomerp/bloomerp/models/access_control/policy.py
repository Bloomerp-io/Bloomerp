from django.db import models
from django.utils.translation import gettext_lazy as _, gettext_noop
from django.contrib.auth.models import Group, Permission
from django.contrib.auth import get_user_model
from django.conf import settings

from bloomerp.models.access_control import RowPolicy
from bloomerp.models.access_control.field_policy import FieldPolicy
from bloomerp.models.definition import FieldLayout, LayoutItem, LayoutRow
from bloomerp.models.definition import BloomerpModelConfig, DetailViewSettings
from bloomerp.models.mixins import TimestampModelMixin
from django.contrib.contenttypes.models import ContentType
from django.db.models import QuerySet
from bloomerp.models.mixins.user_stamp_model_mixin import UserStampModelMixin
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.models.mixins import absolute_url_model_mixin
from bloomerp.models.application_field import ApplicationField
from bloomerp.permissions.definition import AccessRule, RowPolicyRuleContent

class Policy(
    TimestampModelMixin,
    UserStampModelMixin,
    absolute_url_model_mixin.AbsoluteUrlModelMixin,
    models.Model):
    """
    Represents an access control policy, which combines row-level and field-level policies.
    """
    class Meta:
        db_table = "bloomerp_access_control_policy"
        verbose_name = _("Access Control Policy")
        verbose_name_plural = _("Access Control Policies")
    
    bloomerp_config = BloomerpModelConfig(
        detail_view_settings=DetailViewSettings(
            layouts=[FieldLayout(
                rows=[
                LayoutRow(
                    title=gettext_noop("Policy Details"),
                    columns=4,
                    items=[
                        LayoutItem(id="name", colspan=2),
                        LayoutItem(id="users", colspan=1),
                        LayoutItem(id="groups", colspan=1),
                        LayoutItem(id="description", colspan=4),
                    ],
                ),
                LayoutRow(
                    title=gettext_noop("Policy Scope"),
                    columns=4,
                    items=[
                        LayoutItem(id="row_policy", colspan=2),
                        LayoutItem(id="field_policy", colspan=2),
                    ],
                ),
                LayoutRow(
                    title=gettext_noop("Statistics"),
                    columns=4,
                    items=[
                        LayoutItem(id="number_of_users", colspan=2),
                    ],
                ),
                ]
            )],
        )
    )


    name = models.CharField(
            max_length=255,
            help_text=_("The name of the access control policy."),
        verbose_name=_("Name"),
        )

    description = models.TextField(
        blank=True,
        help_text=_("A description of the access control policy."),
        verbose_name=_("Description"),
    )

    system_created = models.BooleanField(default=False, editable=False)
    default_policy_key = models.CharField(
        max_length=512, unique=True, null=True, blank=True, editable=False,
    )
    default_policy_hash = models.CharField(
        max_length=64, blank=True, default="", editable=False,
    )
    
    row_policy = models.ForeignKey(
        to=RowPolicy,
        on_delete=models.CASCADE,
        related_name='policies',
        help_text=_("The row-level policy associated with this access control policy."),
        verbose_name=_("Row Policy"),
    )
    
    field_policy = models.ForeignKey(
        to=FieldPolicy,
        on_delete=models.CASCADE,
        related_name='policies',
        help_text=_("The field-level policy associated with this access control policy."),
        verbose_name=_("Field Policy"),
    )

    users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name='access_control_policies',
        blank=True,
        help_text=_("Users assigned to this access control policy."),
        verbose_name=_("Users"),
    )

    groups = models.ManyToManyField(
        Group,
        related_name='access_control_policies',
        blank=True,
        help_text=_("Groups assigned to this access control policy."),
        verbose_name=_("Groups"),
    )

    global_permissions = models.ManyToManyField(
        Permission,
        related_name='access_control_policies',
        blank=True,
        help_text=_("Global permissions applied by this policy."),
        verbose_name=_("Global Permissions"),
    )
    
    def __str__(self):
        return f"{self.name}"

    @property
    def number_of_users(self) -> int:
        """Returns the total number of users assigned to this policy, including those in groups."""
        return self.get_users().count()
    
    @staticmethod
    def get_policies_for_model(model: models.Model):
        """Retrieve all policies associated with a specific model."""
        return Policy.objects.filter(
            row_policy__content_type_id=ContentType.objects.get_for_model(model).id
        )
        
    def assign_user(self, user: AbstractBloomerpUser):
        """Assigns a single user to this policy.

        Raises:
            TypeError: if `user` is not an instance of the project's user model.
        """
        if not isinstance(user, AbstractBloomerpUser):
            raise TypeError("user must be an AbstractBloomerpUser instance")
        if not self.pk:
            self.save()
        self.users.add(user)

    def assign_users(self, users: QuerySet[AbstractBloomerpUser]):
        """Assign multiple users to this policy. Accepts a QuerySet or any iterable of users."""
        if users is None:
            return
        if not self.pk:
            self.save()
        # Allow passing a QuerySet or an iterable/list of user instances
        try:
            self.users.add(*users)
        except TypeError:
            # Fallback: iterate and validate individual items
            for user in users:
                if not isinstance(user, AbstractBloomerpUser):
                    raise TypeError("all elements must be AbstractBloomerpUser instances")
                self.users.add(user)

    def assign_group(self, group: Group):
        """Assign a single group to this policy.

        Raises:
            TypeError: if `group` is not a django `Group` instance.
        """
        if not isinstance(group, Group):
            raise TypeError("group must be a django.contrib.auth.models.Group instance")
        if not self.pk:
            self.save()
        self.groups.add(group)

    def assign_groups(self, groups: QuerySet[Group]):
        """Assign multiple groups to this policy. Accepts a QuerySet or any iterable of groups."""
        if groups is None:
            return
        if not self.pk:
            self.save()
        try:
            self.groups.add(*groups)
        except TypeError:
            for group in groups:
                if not isinstance(group, Group):
                    raise TypeError("all elements must be django.contrib.auth.models.Group instances")
                self.groups.add(group)
                
    def get_users(self) -> QuerySet[AbstractBloomerpUser]:
        """Return a QuerySet of users who have this policy either directly
        assigned or via membership of one of the policy's groups.
        """
        User = get_user_model()
        # IDs of users directly assigned
        direct_user_ids = self.users.values_list('pk', flat=True)
        # Users who are members of any of the assigned groups
        group_qs = self.groups.all()
        return User.objects.filter(models.Q(pk__in=direct_user_ids) | models.Q(groups__in=group_qs)).distinct()
    
    def to_access_rule(self) -> AccessRule:
        """Creates an access rule out of the policy

        Returns:
            AccessRule: the access rule that exists from the policy
        """
        row_permissions = []
        if self.row_policy_id:
            for rule in self.row_policy.rules.all():
                try:
                    content = RowPolicyRuleContent.model_validate(rule.rule)
                    row_permissions.append(
                        content.model_copy(
                            update={
                                "permissions": list(
                                    rule.permissions.values_list("codename", flat=True)
                                )
                            }
                        )
                    )
                except Exception:
                    continue

        field_permissions = {}
        if self.field_policy_id and isinstance(self.field_policy.rule, dict):
            for field_id, permissions in self.field_policy.rule.items():
                if field_id == "__all__":
                    for application_field_id in ApplicationField.objects.filter(
                        content_type=self.field_policy.content_type
                    ).values_list("pk", flat=True):
                        key = str(application_field_id)
                        field_permissions[key] = list(
                            dict.fromkeys(
                                [*field_permissions.get(key, []), *(permissions or [])]
                            )
                        )
                else:
                    key = str(field_id)
                    field_permissions[key] = list(
                        dict.fromkeys(
                            [*field_permissions.get(key, []), *(permissions or [])]
                        )
                    )

        return AccessRule(
            row_permissions=row_permissions,
            field_permissions=field_permissions,
        )
