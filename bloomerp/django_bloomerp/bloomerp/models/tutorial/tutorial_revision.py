"""Draft and published versions of tutorial content."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar
from uuid import UUID

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import Exists, OuterRef, QuerySet, Subquery
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext, gettext_noop
from django.utils.translation import gettext_lazy as _
from django_htmx.http import HttpResponseClientRefresh, trigger_client_event

from bloomerp.models.base_bloomerp_model import BloomerpModel
from bloomerp.models.definition import (
    ApiSettings,
    BloomerpModelConfig,
    ObjectAction,
    ObjectActionContext,
    ObjectActionDefinition,
    SearchSettings,
)
from bloomerp.models.actions.object.builtins import get_default_object_actions
from bloomerp.permissions.definition import BloomerpPermission, PermissionMatch

from .tutorial_step import TutorialStep

if TYPE_CHECKING:
    from django.contrib.auth.base_user import AbstractBaseUser

    from bloomerp.permissions.manager import UserPolicyManager


def can_render_edit_revision(
    context: ObjectActionContext, *, fields: list[str] | None = None
) -> bool:
    """Check draft access and any fields required by the action."""
    from bloomerp.permissions.manager import UserPolicyManager

    revision = context.object
    user = context.request.user
    if (
        not isinstance(revision, TutorialRevision)
        or revision.published_at is not None
        or not user.is_authenticated
    ):
        return False

    permissions = UserPolicyManager(user)
    required = [BloomerpPermission.VIEW, BloomerpPermission.CHANGE]
    return permissions.has_access_to_object(
        revision, required, fields=fields, match=PermissionMatch.ALL
    ) and permissions.has_access_to_object(
        revision.tutorial, required, match=PermissionMatch.ALL
    )


def edit_revision_button_attrs(context: ObjectActionContext) -> dict[str, str]:
    """Pass the selected draft ID to the existing tutorial editor."""
    return {
        "data-tutorial-revision-id": str(context.object.pk),
        "onclick": (
            "this.dispatchEvent(new CustomEvent('bloomerp:tutorial-edit', { bubbles: true }))"
        ),
    }


def can_render_publish_revision(context: ObjectActionContext) -> bool:
    """Offer publication to authors with access to the publication field."""
    return can_render_edit_revision(context, fields=["published_at"])


def publish_revision_action(context: ObjectActionContext) -> HttpResponse:
    """Timestamp and lock the draft for publication, then refresh its row."""
    from bloomerp.permissions.manager import UserPolicyManager

    user = context.request.user
    permissions = UserPolicyManager(user)
    required = [BloomerpPermission.VIEW, BloomerpPermission.CHANGE]
    with transaction.atomic():
        revision = TutorialRevision.get_writable(
            permissions, context.object.pk, lock=True
        )
        if not permissions.has_access_to_object(
            revision, required, fields=["published_at"], match=PermissionMatch.ALL
        ):
            raise PermissionDenied
        revision.published_at = timezone.now()
        revision.updated_by = user
        revision.save(update_fields=["published_at", "updated_by", "datetime_updated"])

    messages.success(context.request, gettext("Tutorial revision published."))
    return trigger_client_event(
        HttpResponseClientRefresh(),
        "bloomerp:tutorial-published",
        {"revisionId": str(revision.pk), "target": "body"},
    )


def tutorial_revision_object_actions(
    model: type[models.Model],
) -> list[ObjectActionDefinition]:
    """Add editing and publication to the standard revision actions."""
    return [
        *get_default_object_actions(model),
        ObjectAction(
            id="edit-revision",
            label=gettext_noop("Edit"),
            icon="fa-solid fa-pencil",
            button_attrs=edit_revision_button_attrs,
            should_render_func=can_render_edit_revision,
        ),
        ObjectAction(
            id="publish-revision",
            label=gettext_noop("Publish"),
            icon="fa-solid fa-upload",
            execution_func=publish_revision_action,
            should_render_func=can_render_publish_revision,
        ),
    ]


TUTORIAL_REVISION_CONFIG = BloomerpModelConfig(
    is_internal=True,
    api_settings=ApiSettings(enable_auto_generation=False),
    string_search_settings=SearchSettings(
        allow_global_search=False, include_search_routes=False
    ),
    object_actions=tutorial_revision_object_actions,
)


class TutorialRevision(BloomerpModel):
    """Version the steps and settings that determine when a tutorial opens."""

    class Meta(BloomerpModel.Meta):
        db_table = "bloomerp_tutorial_revision"
        ordering = ("-number",)
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=("tutorial", "number"), name="tutorial_revision_unique_number"
            ),
            models.CheckConstraint(
                condition=models.Q(number__gte=1),
                name="tutorial_revision_positive_number",
            ),
            models.CheckConstraint(
                condition=models.Q(auto_start=False) | ~models.Q(trigger_route=""),
                name="tutorial_revision_auto_requires_route",
            ),
        ]

    bloomerp_config = TUTORIAL_REVISION_CONFIG

    tutorial = models.ForeignKey(
        "bloomerp.Tutorial",
        on_delete=models.CASCADE,
        related_name="revisions",
        verbose_name=_("Tutorial"),
    )
    number = models.PositiveIntegerField(
        validators=[MinValueValidator(1)], verbose_name=_("Revision number")
    )
    trigger_route = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("Trigger route"),
        help_text=_("Django URL name for the page where this tutorial is offered."),
    )
    auto_start = models.BooleanField(
        default=False, verbose_name=_("Start automatically")
    )
    published_at = models.DateTimeField(
        null=True, blank=True, editable=False, verbose_name=_("Published at")
    )

    @classmethod
    def eligible_for(cls, user: AbstractBaseUser) -> QuerySet[TutorialRevision]:
        """Return the current nonempty published revision of each eligible tutorial."""
        from .tutorial import Tutorial

        audience = Tutorial.audience_for(user)
        latest = cls.objects.filter(
            tutorial_id=OuterRef("tutorial_id"), published_at__isnull=False
        ).order_by("-number")
        return cls.objects.filter(
            tutorial_id__in=audience.values("pk"),
            pk=Subquery(latest.values("pk")[:1]),
        ).filter(Exists(TutorialStep.objects.filter(revision_id=OuterRef("pk"))))

    @classmethod
    def get_writable(
        cls, permissions: UserPolicyManager, revision_id: UUID | int, *, lock: bool = False
    ) -> TutorialRevision:
        """Find an editable draft and optionally serialize writes to its steps."""
        change = BloomerpPermission.CHANGE
        if not permissions.has_global_permission(cls, change):
            raise PermissionDenied()
        if not isinstance(revision_id, UUID):
            raise Http404

        writable_ids = (
            permissions.get_accessible_queryset(cls, change).order_by().values("pk")
        )
        revisions = cls.objects.filter(pk__in=writable_ids, published_at__isnull=True)
        if lock:
            revisions = revisions.select_for_update()
        revision = get_object_or_404(revisions, pk=revision_id)
        if not permissions.has_access_to_object(
            revision.tutorial,
            [BloomerpPermission.VIEW, change],
            match=PermissionMatch.ALL,
        ):
            raise PermissionDenied()
        return revision

    def next_step_sequence(self) -> int:
        """Return the next sequence for a caller holding the draft lock."""
        last_sequence = (
            self.steps.order_by("-sequence").values_list("sequence", flat=True).first()
        )
        return 1 if last_sequence is None else last_sequence + 1

    def steps_with_sequence_access(
        self,
        permissions: UserPolicyManager,
        action: BloomerpPermission,
    ) -> QuerySet[TutorialStep]:
        """Scope steps to the caller's row and sequence field grants for an action."""
        from bloomerp.models.application_field import ApplicationField
        from bloomerp.permissions.manager import field_access_annotation_name

        steps = permissions.get_accessible_queryset(TutorialStep, action).filter(
            revision=self
        )
        if permissions.user.is_superuser:
            return steps

        sequence_field = ApplicationField.get_by_field(TutorialStep, "sequence")
        if sequence_field is None:
            raise PermissionDenied()
        steps = permissions.annotate_field_permissions(steps, [sequence_field], action)
        return steps.filter(**{field_access_annotation_name(sequence_field): True})

    def __str__(self) -> str:
        """Identify the revision by tutorial name and revision number."""
        return _("%(tutorial)s (revision %(number)s)") % {
            "tutorial": self.tutorial,
            "number": self.number,
        }
