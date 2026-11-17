"""Page validation layered on the generated model serializer and CRUD routes."""

from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils.translation import gettext as _
from rest_framework import serializers
from rest_framework.exceptions import APIException, PermissionDenied

from bloomerp.models.files.page import Page
from bloomerp.utils.api import generate_serializer


class PageConflict(APIException):
    """Report a stale page save without replacing either editor's content."""

    status_code = 409
    default_detail = _("This page changed elsewhere. Reload before continuing to edit.")


class PageSerializer(generate_serializer(Page)):
    """Keep ownership, sharing, references and optimistic saves on the generated API."""

    def get_fields(self) -> dict[str, serializers.Field]:
        """Default new ownership to the caller and protect identity and audit fields."""
        fields = super().get_fields()
        if self.instance is None:
            fields["owner"].default = serializers.CurrentUserDefault()
        fields["owner"].required = False
        for name in (
            "id",
            "created_by",
            "updated_by",
            "datetime_created",
            "datetime_updated",
        ):
            fields[name].read_only = True
        return fields

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Reject ownership changes and sharing by collaborators before saving relations."""
        request = self.context["request"]
        if self.instance is None:
            if attrs.get("owner", request.user) != request.user:
                raise PermissionDenied(_("New pages must belong to you."))
        elif "owner" in attrs and attrs["owner"].pk != self.instance.owner_id:
            raise PermissionDenied(_("Page ownership cannot be changed."))
        if (
            self.instance
            and not self.instance.can_manage(request.user)
            and {"shared_with_users", "shared_with_groups"} & attrs.keys()
        ):
            raise PermissionDenied(_("Only the owner can change page sharing."))
        return super().validate(attrs)

    @transaction.atomic
    def create(self, validated_data: dict[str, Any]) -> Page:
        """Create a personal page through generated CRUD and record its first edit."""
        request = self.context["request"]
        candidate = Page(owner=request.user)
        content, references = self.prepare_content(
            candidate, validated_data.get("content", "")
        )
        validated_data.update(
            owner=request.user,
            content=content,
            created_by=request.user,
            updated_by=request.user,
        )
        page = super().create(validated_data)
        self.finish_edit(page, references)
        return page

    @transaction.atomic
    def update(self, instance: Page, validated_data: dict[str, Any]) -> Page:
        """Lock the current revision and reject stale autosaves before writing content."""
        request = self.context["request"]
        current = Page.objects.select_for_update().get(pk=instance.pk)
        if not Page.accessible_to(request.user).filter(pk=current.pk).exists():
            raise PermissionDenied(_("This page is no longer available to you."))
        expected = request.headers.get("If-Match")
        if (
            expected is not None
            and expected.strip('"') != current.datetime_updated.isoformat()
        ):
            raise PageConflict
        references = None
        if "content" in validated_data:
            validated_data["content"], references = self.prepare_content(
                current, validated_data["content"]
            )
        content_changed = any(
            name in validated_data and validated_data[name] != getattr(current, name)
            for name in ("title", "content")
        )
        validated_data["updated_by"] = request.user
        page = super().update(current, validated_data)
        if content_changed:
            self.finish_edit(page, references)
        else:
            page.notify_changed()
        return page

    def prepare_content(
        self, page: Page, content: str
    ) -> tuple[str, dict[int, list[Any]]]:
        """Translate model reference validation failures into normal API field errors."""
        try:
            return page.prepare_content(self.context["request"], content)
        except DjangoValidationError as error:
            raise serializers.ValidationError({"content": error.messages}) from error

    def finish_edit(self, page: Page, references: dict[int, list[Any]] | None) -> None:
        """Persist embedded references and announce the committed page revision."""
        try:
            page.reconcile_content_references(self.context["request"], references)
        except DjangoValidationError as error:
            raise serializers.ValidationError({"content": error.messages}) from error
        page.notify_changed()

    def to_representation(self, instance: Page) -> dict[str, Any]:
        """Hide sharing recipients from collaborators who cannot manage the page."""
        data = super().to_representation(instance)
        data["datetime_updated"] = (
            instance.datetime_updated.isoformat() if instance.datetime_updated else None
        )
        request = self.context.get("request")
        if request is not None and not instance.can_manage(request.user):
            data.pop("shared_with_users", None)
            data.pop("shared_with_groups", None)
        return data
