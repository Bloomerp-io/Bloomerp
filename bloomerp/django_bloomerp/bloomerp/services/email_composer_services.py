"""Account selection and permission-aware template data for outbound email."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django import forms
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import FieldDoesNotExist, PermissionDenied, ValidationError
from django.db import models
from django.http import Http404, QueryDict
from django.shortcuts import get_object_or_404
from django.template import Context, Engine, TemplateDoesNotExist, TemplateSyntaxError
from django.utils.translation import gettext as _

from bloomerp.communication.utils.permissions import accessible_inbox_folders
from bloomerp.models.communication.email_account import EmailAccount
from bloomerp.models.document_templates import DocumentTemplate
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.services.document_services import DocumentTemplateService


def accessible_email_accounts(user: AbstractBloomerpUser) -> models.QuerySet[EmailAccount]:
    """Allow existing shared-inbox senders and policy-readable email accounts."""
    manager = UserPolicyManager(user)
    permitted_ids = []
    if manager.has_global_permission(EmailAccount, "view"):
        for account in manager.get_accessible_queryset(EmailAccount, "view"):
            if manager.has_access_to_object(account, "view", fields=["email_address"]):
                permitted_ids.append(account.pk)
    folders = accessible_inbox_folders(user).filter(type="email")
    for identifier in folders.values_list("related_object_id", flat=True):
        try:
            permitted_ids.append(UUID(identifier))
        except (ValueError, TypeError, AttributeError):
            continue
    return EmailAccount.objects.filter(pk__in=permitted_ids).order_by("email_address")


def resolve_email_object(user: AbstractBloomerpUser, data: QueryDict) -> models.Model | None:
    """Resolve optional composer context with model and row permission checks."""
    content_type_id, object_id = data.get("content_type_id"), data.get("object_id")
    if not content_type_id and not object_id:
        return None
    if not content_type_id or not object_id:
        raise ValidationError(_("Both the object and its content type are required."))
    try:
        content_type = get_object_or_404(ContentType, pk=content_type_id)
        model = content_type.model_class()
        if model is None:
            raise Http404
        manager = UserPolicyManager(user)
        if not manager.has_global_permission(model, "view"):
            raise PermissionDenied
        return get_object_or_404(manager.get_accessible_queryset(model, "view"), pk=object_id)
    except (ValueError, TypeError, ValidationError) as exc:
        raise ValidationError(_("Invalid email object.")) from exc


def email_fields_for_object(user: AbstractBloomerpUser, obj: models.Model) -> list[dict[str, str]]:
    """List populated, readable direct email fields for the detail-view action."""
    manager = UserPolicyManager(user)
    if not manager.has_access_to_object(obj, "view"):
        return []
    readable = set(manager.get_accessible_fields_for_object(obj, "view").values_list("field", flat=True))
    return [
        {"name": field.name, "label": str(field.verbose_name), "value": str(getattr(obj, field.name))}
        for field in obj._meta.fields
        if isinstance(field, models.EmailField)
        and field.name in readable
        and getattr(obj, field.name)
    ]


def matching_email_templates(user: AbstractBloomerpUser, obj: models.Model | None) -> list[DocumentTemplate]:
    """Offer every readable document template regardless of the object context."""
    from bloomerp.services.document_template_selection import readable_document_templates

    return readable_document_templates(user)


def resolve_email_template(
    user: AbstractBloomerpUser, obj: models.Model | None, template_id: str | None,
) -> DocumentTemplate | None:
    """Reject template IDs outside the current user's readable set."""
    if not template_id:
        return None
    for template in matching_email_templates(user, obj):
        if str(template.pk) == template_id:
            return template
    raise Http404


def resolve_email_templates(
    user: AbstractBloomerpUser, obj: models.Model | None, data: QueryDict,
) -> list[DocumentTemplate]:
    """Resolve every distinct inserted template through the existing access checks."""
    ids = list(dict.fromkeys(value for value in data.getlist("document_template_id") if value))
    templates: list[DocumentTemplate] = []
    for template_id in ids:
        template = resolve_email_template(user, obj, template_id)
        if template is not None:
            templates.append(template)
    return templates


def email_template_form(
    template: DocumentTemplate, user: AbstractBloomerpUser,
    obj: models.Model | None, data: QueryDict | None = None,
) -> forms.Form:
    """Reuse document variables while scoping every selectable root object."""
    service = DocumentTemplateService(template, user)
    form = service.get_form(instance=obj)(data=data, prefix="template_args")
    form.fields.pop("persist", None)
    manager = UserPolicyManager(user)

    def readable_label(instance: models.Model) -> str:
        """Build a recognizable choice label without using unrestricted __str__."""
        readable = set(manager.get_accessible_fields_for_object(instance, "view").values_list("field", flat=True))
        for name in ("name", "title", "email_address", "username", "first_name"):
            if name in readable:
                return str(getattr(instance, name) or instance.pk)
        return str(instance.pk)

    for field in form.fields.values():
        if isinstance(field, forms.ModelChoiceField):
            model = field.queryset.model
            field.label_from_instance = readable_label
            field.queryset = (
                manager.get_accessible_queryset(model, "view")
                if manager.has_global_permission(model, "view") else model.objects.none()
            )
        field.widget.attrs.setdefault("class", "input w-full")
    return form


class EmailTemplateObject(dict[str, Any]):
    """Expose only readable model fields, never arbitrary methods, to templates."""

    def __init__(self, obj: models.Model, manager: UserPolicyManager) -> None:
        """Keep the source private and cache the object's readable field names."""
        self._object = obj
        self._manager = manager
        self._fields = set(manager.get_accessible_fields_for_object(obj, "view").values_list("field", flat=True))

    def __getitem__(self, name: str) -> Any:
        """Resolve authorized scalar and related fields without leaking model APIs."""
        if name.startswith("_") or name not in self._fields:
            raise PermissionDenied(_("The email references a field you cannot view."))
        try:
            field = self._object._meta.get_field(name)
        except FieldDoesNotExist as exc:
            raise PermissionDenied(_("Only model fields can be used in email templates.")) from exc
        value = getattr(self._object, name)
        if field.is_relation:
            if value is None:
                return None
            if field.one_to_many or field.many_to_many:
                if not self._manager.has_global_permission(field.related_model, "view"):
                    raise PermissionDenied
                queryset = value.all().filter(
                    pk__in=self._manager.get_accessible_queryset(field.related_model, "view"),
                )
                return [EmailTemplateObject(item, self._manager) for item in queryset]
            if not self._manager.has_access_to_object(value, "view"):
                raise PermissionDenied
            return EmailTemplateObject(value, self._manager)
        return str(value) if isinstance(field, models.FileField) else value

    def get(self, name: str, default: Any = None) -> Any:
        """Route document-table mapping lookups through the field permission gate."""
        return self[name]

    def __bool__(self) -> bool:
        """Treat an authorized root as present despite its lazily resolved fields."""
        return True

    def __str__(self) -> str:
        """Avoid implicit model stringification exposing an unreadable label field."""
        return str(self._object.pk)


def render_email_body(
    user: AbstractBloomerpUser, obj: models.Model | None,
    template: DocumentTemplate | list[DocumentTemplate] | None, data: QueryDict,
) -> str:
    """Resolve variables against the edited message without changing its template."""
    body = data.get("body", "")
    templates = template if isinstance(template, list) else ([template] if template else [])
    if not templates:
        return body
    manager = UserPolicyManager(user)
    roots: dict[str, EmailTemplateObject] = {}
    variables: dict[str, Any] = {}
    for inserted_template in templates:
        form = email_template_form(inserted_template, user, obj, data)
        if not form.is_valid():
            raise ValidationError([
                f"{form.fields[name].label or name}: {message}"
                for name, messages in form.errors.items() for message in messages
            ])
        service = DocumentTemplateService(inserted_template, user)
        for name, value in service.get_cleaned_model_variable_values(form).items():
            roots[name] = EmailTemplateObject(value, manager)
        for name, value in service.get_cleaned_free_variable_values(form).items():
            if name in variables and variables[name] != value:
                raise ValidationError(_("Inserted templates define incompatible values for variable %(name)s.") % {"name": name})
            variables[name] = value
    context = {
        **roots,
        "object": EmailTemplateObject(obj, manager) if obj is not None else next(iter(roots.values()), None),
        "objects": list(roots.values()),
        "vars": variables,
    }
    # Edited emails cannot load application templates or additional tag libraries.
    engine = Engine(
        loaders=[],
        libraries={
            "document_template_tags": "bloomerp.templatetags.document_template_tags",
            "humanize": "django.contrib.humanize.templatetags.humanize",
        },
    )
    try:
        source = "{% load document_template_tags humanize %}" + body
        return engine.from_string(source).render(Context(context))
    except (TemplateSyntaxError, TemplateDoesNotExist) as exc:
        raise ValidationError(_("Invalid email template: %(error)s"), params={"error": str(exc)}) from exc
