"""Personal rich-text pages with explicit user and group sharing."""

from __future__ import annotations

from functools import partial
from typing import Any, ClassVar
from uuid import UUID

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import models, transaction
from django.db.models import Exists, OuterRef, Q, Subquery, Value
from django.db.models.functions import Cast, Replace
from django.http import HttpRequest
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from bloomerp.filters.definition import FilterCondition
from bloomerp.models import BloomerpModel
from bloomerp.models.definition import (
    ApiAccessSettings,
    ApiSettings,
    BloomerpModelConfig,
    DetailViewSettings,
    ModelViewSettings,
)
from bloomerp.modules.file_management import FileManagement
from bloomerp.permissions.definition import AccessRule, RowPolicyRuleContent
from bloomerp.permissions.manager import UserPolicyManager

PAGE_ACCESS = AccessRule(
    row_permissions=[
        RowPolicyRuleContent(
            permissions=["view", "change"],
            connector="OR",
            conditions=[
                FilterCondition(field_path="owner", lookup_id="equals", value="$user"),
                FilterCondition(
                    field_path="shared_with_users__pk",
                    lookup_id="equals",
                    value="$user",
                ),
                FilterCondition(
                    field_path="shared_with_groups__user__pk",
                    lookup_id="equals",
                    value="$user",
                ),
            ],
        )
    ],
    field_permissions={
        "title": ["view", "change"],
        "content": ["view", "change"],
        "owner": ["view"],
        "datetime_updated": ["view", "change"],
        "id": ["view", "change"],
    },
)


PAGE_OWNER_ACCESS = AccessRule(
    row_permissions=[
        RowPolicyRuleContent(
            permissions=["add", "view", "change", "delete"],
            conditions=[
                FilterCondition(field_path="owner", lookup_id="equals", value="$user")
            ],
        )
    ],
    field_permissions={
        name: ["add", "view", "change"]
        for name in (
            "id",
            "title",
            "content",
            "owner",
            "datetime_updated",
            "shared_with_users",
            "shared_with_groups",
        )
    },
)


class Page(BloomerpModel):
    """Store a page whose owner controls sharing and deletion."""

    class Meta(BloomerpModel.Meta):
        db_table = "bloomerp_page"
        verbose_name = _("Page")
        verbose_name_plural = _("Pages")
        ordering: ClassVar[list[str]] = ["-datetime_updated", "id"]

    bloomerp_config = BloomerpModelConfig(
        module=FileManagement,
        icon="fa-regular fa-file-lines",
        description="Personal and shared rich-text pages.",
        api_settings=ApiSettings(
            enable_auto_generation=True,
            serializer_class="bloomerp.serializers.page.PageSerializer",
            access=ApiAccessSettings(authenticated=[PAGE_ACCESS, PAGE_OWNER_ACCESS]),
        ),
        # The dedicated editor owns editing and autosave; avoid a second generic UI.
        model_view_settings=ModelViewSettings(
            skip_views=["add", "bulk_upload", "files"]
        ),
        detail_view_settings=DetailViewSettings(
            skip_views=["overview", "delete", "files", "todos", "document_templates"]
        ),
    )
    avatar = None
    title = models.CharField(
        max_length=255, blank=True, default="", verbose_name=_("Title")
    )
    content = models.TextField(blank=True, default="", verbose_name=_("Content"))
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="owned_pages",
        verbose_name=_("Owner"),
    )
    shared_with_users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="shared_pages",
        verbose_name=_("Shared with users"),
    )
    shared_with_groups = models.ManyToManyField(
        "auth.Group",
        blank=True,
        related_name="shared_pages",
        verbose_name=_("Shared with groups"),
    )

    @classmethod
    def accessible_to(cls, user: Any) -> models.QuerySet[Page]:
        """Compile the same owner/share grants used for embedded file access."""
        if not user.is_authenticated:
            return cls.objects.none()
        if user.is_superuser:
            return cls.objects.all()
        return UserPolicyManager(user).get_queryset_for_access_rules(
            cls, [PAGE_ACCESS], "view"
        )

    @classmethod
    def recent_for(cls, user: Any) -> models.QuerySet[Page]:
        """Return the ten accessible pages most recently edited by this user."""
        from bloomerp.models.audit.activity_log import ActivityLog, ActivityLogAction

        # JSON index lookups work on both SQLite and PostgreSQL. The standard
        # logger emits at most one change per serialized model field.
        content_edit = Q(action=ActivityLogAction.CREATE) | Q(
            action=ActivityLogAction.CHANGE, payload=[]
        )
        for index in range(len(cls._meta.get_fields())):
            content_edit |= Q(
                action=ActivityLogAction.CHANGE,
                **{f"payload__{index}__field__in": ["title", "content"]},
            )
        edits = (
            ActivityLog.objects.annotate(
                page_key=Replace("object_id", Value("-"), Value(""))
            )
            .filter(
                content_type=ContentType.objects.get_for_model(cls),
                page_key=Replace(
                    Cast(OuterRef("pk"), output_field=models.CharField()),
                    Value("-"),
                    Value(""),
                ),
                actor=user,
            )
            .filter(content_edit)
            .order_by("-timestamp")
        )
        return (
            cls.accessible_to(user)
            .annotate(last_edited_at=Subquery(edits.values("timestamp")[:1]))
            .filter(last_edited_at__isnull=False)
            .order_by("-last_edited_at", "pk")[:10]
        )

    @classmethod
    def shared_for(cls, user: Any) -> models.QuerySet[Page]:
        """Include pages shared with the user and owned pages shared with anyone."""
        users = cls.shared_with_users.through.objects.filter(page_id=OuterRef("pk"))
        groups = cls.shared_with_groups.through.objects.filter(page_id=OuterRef("pk"))
        return cls.accessible_to(user).filter(Exists(users) | Exists(groups))

    @classmethod
    def private_for(cls, user: Any) -> models.QuerySet[Page]:
        """Return only this user's pages that have no user or group shares."""
        return cls.accessible_to(user).filter(
            owner=user, shared_with_users__isnull=True, shared_with_groups__isnull=True
        )

    def prepare_content(
        self, request: HttpRequest, content: str
    ) -> tuple[str, dict[int, list[Any]]]:
        """Sanitize rich text and validate its references before an API write."""
        from bloomerp.models import ApplicationField
        from bloomerp.services.object_reference_services import (
            parse_editor_references,
            validate_reference,
        )
        from bloomerp.utils.rich_text import sanitize_html

        field = ApplicationField.objects.get(
            content_type=ContentType.objects.get_for_model(Page), field="content"
        )
        html, references = parse_editor_references(
            sanitize_html(content, allow_images=True), field
        )
        for reference in references:
            validate_reference(request, reference, self)
        return html, {field.pk: references}

    def reconcile_content_references(
        self, request: HttpRequest, references: dict[int, list[Any]] | None = None
    ) -> None:
        """Keep embedded files aligned with the content saved through the API."""
        from bloomerp.services.object_reference_services import reconcile_references

        if references is not None:
            reconcile_references(self, references, None, request)

    def notify_changed(self) -> None:
        """Publish a revision invalidation after commit; clients read via the generated API."""
        transaction.on_commit(
            partial(publish_page_change, self.pk, self.datetime_updated.isoformat())
        )

    def can_manage(self, user: Any) -> bool:
        """Reserve sharing and deletion for the owner and administrators."""
        return user.is_authenticated and (user.is_superuser or self.owner_id == user.pk)

    def get_absolute_url(self) -> str:
        """Open this page in the dedicated model list editor."""
        return f"{reverse('pages_model')}?page={self.pk}"

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        """Invalidate open editors when the generated API deletes a page."""
        identifier = self.pk
        with transaction.atomic():
            result = super().delete(*args, **kwargs)
            transaction.on_commit(partial(publish_page_change, identifier, "deleted"))
        return result

    def __str__(self) -> str:
        """Use the title as the page label, including for untitled drafts."""
        return self.title or str(_("Untitled"))


def publish_page_change(identifier: UUID, version: str) -> None:
    """Notify authorized page sockets without broadcasting private document content."""
    layer = get_channel_layer()
    if layer is not None:
        async_to_sync(layer.group_send)(
            f"page.{identifier.hex}", {"type": "page.changed", "version": version}
        )
