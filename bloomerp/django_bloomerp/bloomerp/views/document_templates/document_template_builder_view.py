
import json
from typing import Any

from bloomerp.forms.core import BloomerpModelForm
from bloomerp.router import router
from bloomerp.models import ApplicationField
from bloomerp.models.document_templates.document_template import DocumentTemplate, FreeVariableConfig
from bloomerp.views.base import BaseBloomerpView
from bloomerp.widgets.foreign_field_widget import ForeignFieldWidget
from django.views.generic import TemplateView
from django.contrib.contenttypes.models import ContentType
from django import forms
from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from bloomerp.services.document_services import DocumentTemplateService, FreeVariableType
from bloomerp.utils.models import get_detail_view_url
from bloomerp.views.detail.base_detail import BaseBloomerpDetailView

class DocumentTemplateBuilderForm(BloomerpModelForm):

    class Meta:
        model = DocumentTemplate
        fields = [
            "name",
            "content_types",
            "page_orientation",
            "page_size",
            "page_margin",
            "include_page_numbers",
            "styling",
            "template_header",
            "template",
            "free_variables"
        ]

    def clean_free_variables_json(self) -> list[dict[str, Any]]:
        raw_value = self.cleaned_data.get("free_variables_json") or "[]"
        return self.clean_free_variables_payload(raw_value)

    def clean_free_variables(self) -> list[dict[str, Any]]:
        raw_value = self.cleaned_data.get("free_variables") or []
        return self.clean_free_variables_payload(raw_value)

    def clean_free_variables_payload(self, raw_value: Any) -> list[dict[str, Any]]:
        try:
            parsed = json.loads(raw_value) if isinstance(raw_value, str) else raw_value
        except json.JSONDecodeError as exc:
            raise forms.ValidationError("Free variables must be valid JSON.") from exc

        if not isinstance(parsed, list):
            raise forms.ValidationError("Free variables must be a list.")

        configs: list[dict[str, Any]] = []
        seen_slugs: set[str] = set()
        for raw_config in parsed:
            if not isinstance(raw_config, dict):
                raise forms.ValidationError("Each free variable must be an object.")
            try:
                config = FreeVariableConfig(**raw_config)
            except Exception as exc:
                raise forms.ValidationError("One or more free variables are invalid.") from exc
            if not config.normalized_slug:
                raise forms.ValidationError("Each free variable needs a slug.")
            if config.normalized_slug in seen_slugs:
                raise forms.ValidationError(f"Free variable '{config.normalized_slug}' is duplicated.")
            seen_slugs.add(config.normalized_slug)
            configs.append(config.as_json())

        return configs

    def save(self, commit: bool = True):
        instance = super().save(commit=False)
        instance.template = self.cleaned_data.get("template") or ""
        instance.free_variables = self.cleaned_data.get("free_variables", [])
        if commit:
            instance.save()
            self.save_m2m()
        return instance


def get_template_content_types():
    content_type_ids = (
        ApplicationField.objects
        .exclude(content_type__isnull=True)
        .values_list("content_type_id", flat=True)
        .distinct()
    )
    return ContentType.objects.filter(id__in=content_type_ids).order_by("app_label", "model")


def get_selected_content_types(request, instance: DocumentTemplate | None = None) -> list[ContentType]:
    raw_content_type_ids = request.POST.getlist("content_types") or request.GET.getlist("content_types")
    legacy_content_type_id = request.GET.get("content_type_id")
    if not raw_content_type_ids and legacy_content_type_id:
        raw_content_type_ids = [legacy_content_type_id]

    if raw_content_type_ids:
        selected = list(get_template_content_types().filter(pk__in=raw_content_type_ids).order_by("app_label", "model"))
        if selected:
            return selected

    if request.method == "POST":
        return []

    if instance and instance.pk:
        selected = list(instance.content_types.all().order_by("app_label", "model"))
        if selected:
            return selected

    return []


def parse_free_variables_json(raw_value: str) -> list[dict[str, Any]]:
    try:
        parsed = json.loads(raw_value or "[]")
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


class DocumentTemplateBuilderContextMixin:
    template_name = "document_template_views/build_document_template.html"
    model = DocumentTemplate
    htmx_include_addendum_padding = False

    def get_object(self) -> DocumentTemplate | None:
        pk = self.kwargs.get("pk")
        if pk is None:
            return None
        return get_object_or_404(DocumentTemplate, pk=pk)

    def get_initial_object(self) -> DocumentTemplate:
        instance = self.get_object()
        content_types = get_selected_content_types(self.request, instance)
        if instance is not None:
            return instance
        template = DocumentTemplate(
            name="",
            template="",
        )
        template._unsaved_content_types = content_types
        return template

    def get_form(self) -> DocumentTemplateBuilderForm:
        instance = self.get_initial_object()
        if self.request.method == "POST":
            return DocumentTemplateBuilderForm(model=DocumentTemplate, data=self.request.POST, instance=instance)
        return DocumentTemplateBuilderForm(
            model=DocumentTemplate,
            instance=instance,
            initial={"content_types": [content_type.pk for content_type in get_selected_content_types(self.request, instance)]},
        )

    def get_success_url(self) -> str:
        return reverse(get_detail_view_url(DocumentTemplate), kwargs={"pk": self.object.pk})

    def form_valid(self, form: DocumentTemplateBuilderForm):
        with transaction.atomic():
            self.object = form.save(commit=False)
            if hasattr(self.object, "updated_by"):
                self.object.updated_by = self.request.user
            if hasattr(self.object, "created_by") and not self.object.created_by:
                self.object.created_by = self.request.user
            self.object.save()
            form.save_m2m()
        messages.success(self.request, "Document template saved.")
        return redirect(self.get_success_url())

    def form_invalid(self, form: DocumentTemplateBuilderForm):
        return self.render_to_response(self.get_context_data(form=form))

    def post(self, request, *args, **kwargs):
        form = self.get_form()
        if form.is_valid():
            return self.form_valid(form)
        return self.form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        instance = kwargs.get("instance") or self.get_initial_object()
        form = kwargs.get("form") or self.get_form()
        context["builder_form"] = form
        context["free_variable_types"] = FreeVariableType.choices_payload()
        return context


@router.register(
    path="create",
    name="Create {model}",
    url_name="add",
    description="Create a new object from {model}",
    route_type="model",
    models=[DocumentTemplate],
)
class DocumentTemplateBuilderView(DocumentTemplateBuilderContextMixin, BaseBloomerpView, TemplateView):
    pass


@router.register(
    path="builder",
    name="Builder",
    url_name="builder",
    description="Edit a document template with the builder",
    route_type="detail",
    models=[DocumentTemplate],
)
class DocumentTemplateBuilderEditView(DocumentTemplateBuilderContextMixin, BaseBloomerpDetailView):
    pass
