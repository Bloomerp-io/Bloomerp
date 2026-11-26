"""Tutorials authored in an instance or supplied by an installed app."""

from __future__ import annotations

from io import BytesIO
from typing import TYPE_CHECKING, Any, ClassVar
from uuid import UUID

import yaml
from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import FieldError, PermissionDenied, ValidationError
from django.db import models
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.text import slugify
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _
from django.utils.translation import gettext_noop
from django_htmx.http import HttpResponseClientRedirect
from pydantic import TypeAdapter, ValidationError as SchemaValidationError

from bloomerp.dataviews.table.config import TableDataView
from bloomerp.field_types.registry import FieldContext
from bloomerp.filters.compiler import resolve_condition
from bloomerp.filters.definition import Filter, FilterCondition, Filters
from bloomerp.filters.manager import ModelFilterManager
from bloomerp.filters.resolver import FilterFieldResolver
from bloomerp.lookups.definition import CompiledLookup, FilterFieldContext, LookupDefinition
from bloomerp.middleware import current_request
from bloomerp.models.base_bloomerp_model import BloomerpModel
from bloomerp.models.definition import (
    ApiSettings,
    BloomerpModelConfig,
    DataviewAction,
    DataviewActionContext,
    DataviewActionDefinition,
    DetailTab,
    DetailTabsConfiguration,
    DetailViewSettings,
    FieldLayout,
    FieldSettings,
    LayoutItem,
    LayoutRow,
    ModelViewSettings,
    ObjectAction,
    ObjectActionContext,
    ObjectActionDefinition,
    StringSearchSettings,
    get_default_dataview_actions,
)
from bloomerp.models.actions.object.call_dataview import call_dataview_action
from bloomerp.models.actions.object.builtins import get_default_object_actions
from bloomerp.modules.misc import MiscModule
from bloomerp.permissions.definition import BloomerpPermission, PermissionMatch
from bloomerp.utils.requests import render_message
from bloomerp.widgets.filter_widget import FilterWidget
from .tutorial_revision import TutorialRevision
from .tutorial_step import TUTORIAL_STEP_CONTENT_FIELDS
from .tutorial_topic import TutorialTopic

if TYPE_CHECKING:
    from bloomerp.models.application_field import ApplicationField
    from bloomerp.permissions.manager import UserPolicyManager


TUTORIAL_EXPORT_FIELDS = (
    "source_key", "name", "description", "is_active", "available_to_all", "user_filter",
)
REVISION_EXPORT_FIELDS = ("number", "trigger_route", "auto_start", "published_at")
STEP_EXPORT_FIELDS = ("sequence", "key", *TUTORIAL_STEP_CONTENT_FIELDS)
TUTORIAL_YAML_VERSION = 1
_USER_FILTERS = TypeAdapter(Filters)


def parse_tutorial_user_filter(value: object) -> Filters:
    """Read the grouped filter format used by the tutorial's user filter widget."""
    try:
        return _USER_FILTERS.validate_python(value, strict=True)
    except SchemaValidationError as exc:
        raise ValidationError(_("Enter valid grouped user filters.")) from exc


def validate_tutorial_user_filter(value: object) -> None:
    """Validate the user fields, lookups, and values before saving a filter."""
    groups = parse_tutorial_user_filter(value)
    if not groups:
        return
    resolver = FilterFieldResolver.for_model(get_user_model())
    for group in groups:
        for condition in group.conditions:
            _, _, lookup, _value = resolve_condition(condition, resolver=resolver)
            if lookup.get_q_factory() is None:
                raise ValidationError(_("This lookup cannot filter tutorial users."))


def tutorial_user_filter_widget(context: FieldContext) -> FilterWidget:
    """Create an optional filter for the project's configured user model."""
    return FilterWidget(
        model=get_user_model(),
        attrs={
            **context.attrs,
            "data-allow-empty": "true",
            "data-remove-empty-groups": "true",
            "data-track-form-value": "true",
        },
        include_controls=False,
    )


def startable_tutorial_filter(
    _field: ApplicationField, field_path: str, _expression: str, value: bool,
) -> CompiledLookup:
    """Filter tutorials by the current learner's live playback eligibility."""
    user = getattr(current_request(), "user", None)
    if user is None or not user.is_authenticated:
        raise ValidationError("Tutorial eligibility requires a signed-in learner")
    eligible = TutorialRevision.eligible_for(user).order_by().values("tutorial_id")
    predicate = models.Q(**{f"{field_path}__in": eligible})
    return CompiledLookup(predicate=predicate if value else ~predicate)


def startable_tutorial_filter_field(_context: FilterFieldContext) -> forms.BooleanField:
    """Accept a boolean selection for the tutorial eligibility lookup."""
    return forms.BooleanField(required=False)


STARTABLE_TUTORIAL = LookupDefinition(
    id="tutorial_startable",
    label=gettext_noop("Startable tutorial"),
    expressions=("tutorial_startable",),
    q_factory=startable_tutorial_filter,
    default_form_factory=startable_tutorial_filter_field,
)


def can_render_create_revision(context: ObjectActionContext) -> bool:
    """Show the authoring action when the user can start a tutorial revision."""
    return isinstance(context.object, Tutorial) and context.object.can_create_revision(
        context.request.user
    )


def create_revision_button_attrs(context: ObjectActionContext) -> dict[str, str]:
    """Dispatch a browser event to the tutorial component with the creation URL."""
    return {
        "data-tutorial-revision-url": reverse(
            "components_tutorials_create_revision",
            kwargs={"tutorial_id": context.object.pk},
        ),
        "onclick": (
            "this.dispatchEvent(new CustomEvent('bloomerp:tutorial-create', { bubbles: true }))"
        ),
    }


def startable_revision_id(context: ObjectActionContext) -> UUID | None:
    """Find the learner's current published revision, sharing one query across rendered actions."""
    request = context.request
    if not request.user.is_authenticated:
        return None
    if not hasattr(request, "_startable_tutorial_revisions"):
        request._startable_tutorial_revisions = dict(
            TutorialRevision.eligible_for(request.user)
            .order_by()
            .values_list("tutorial_id", "pk")
        )
    return request._startable_tutorial_revisions.get(context.object.pk)


def can_render_start_tutorial(context: ObjectActionContext) -> bool:
    """Show Start tutorial for records the current learner can play."""
    return startable_revision_id(context) is not None


def start_tutorial_button_attrs(context: ObjectActionContext) -> dict[str, str]:
    """Pass the published revision ID to the existing tutorial player."""
    return {"data-tutorial-start-revision": str(startable_revision_id(context))}


def tutorial_revision_filters(context: ObjectActionContext) -> Filters:
    """Limit the Revisions modal to revisions belonging to the current tutorial."""
    return [
        Filter(
            connector="AND",
            conditions=[
                FilterCondition(
                    field_path="tutorial",
                    lookup_id="equals",
                    value=str(context.object.pk),
                ),
            ],
        ),
    ]


def tutorial_object_actions(model: type[models.Model]) -> list[ObjectActionDefinition]:
    """Expose tutorial playback, revision creation, and the revisions modal."""
    return [
        ObjectAction(
            id="start-tutorial",
            label=gettext_noop("Start tutorial"),
            icon="fa-solid fa-play",
            button_attrs=start_tutorial_button_attrs,
            should_render_func=can_render_start_tutorial,
        ),
        ObjectAction(
            id="create-revision",
            label=gettext_noop("Create revision"),
            icon="fa-solid fa-plus",
            button_attrs=create_revision_button_attrs,
            should_render_func=can_render_create_revision,
        ),
        call_dataview_action(
            id="revisions",
            model=TutorialRevision,
            label=gettext_noop("Revisions"),
            icon="fa-solid fa-list",
            filters=tutorial_revision_filters,
        ),
    ]


def can_export_tutorials(_context: DataviewActionContext) -> bool:
    """Show the tutorial YAML action in DEBUG mode."""
    return settings.DEBUG


def export_selected_tutorial(context: DataviewActionContext) -> HttpResponse | FileResponse:
    """Download the selected tutorial as a versioned YAML document."""
    from bloomerp.permissions.manager import UserPolicyManager

    if not settings.DEBUG:
        raise PermissionDenied()
    if len(context.selected_ids) != 1:
        return render_message(
            context.request, gettext("Select one tutorial to export."), "warning",
        )

    tutorial = get_object_or_404(context.queryset, pk=context.selected_ids[0])
    if context.request.headers.get("HX-Request") == "true":
        return HttpResponseClientRedirect(context.request.get_full_path())

    payload = tutorial.get_export_data(UserPolicyManager(context.request.user))
    content = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
    filename = slugify(tutorial.name, allow_unicode=True) or "tutorial"
    response = FileResponse(
        BytesIO(content.encode("utf-8")),
        as_attachment=True,
        filename=f"{filename}.yaml",
        content_type="application/yaml",
    )
    response["Cache-Control"] = "private, no-store"
    return response


def tutorial_dataview_actions(model: type[models.Model]) -> list[DataviewActionDefinition]:
    """Add YAML export to the Tutorials toolbar."""
    return [
        *get_default_dataview_actions(model),
        DataviewAction(
            id="export-tutorial-yaml",
            label=gettext_noop("Export YAML"),
            icon="fa-solid fa-file-arrow-down",
            method="GET",
            should_render_func=can_export_tutorials,
            execution_func=export_selected_tutorial,
            button_attrs={"hx-swap": "beforeend", "hx-push-url": "false"},
        ),
    ]


TUTORIAL_CONFIG = BloomerpModelConfig(
    module=MiscModule,
    description="A tutorial within the BloomERP app",
    api_settings=ApiSettings(enable_auto_generation=False),
    field_settings=[
        FieldSettings(field="user_filter", widget_factory=tutorial_user_filter_widget),
    ],
    string_search_settings=StringSearchSettings(string_search_fields=["name", "description"]),
    detail_view_settings=DetailViewSettings(
        skip_views=["files", "todos", "document_templates"],
        layouts=[
            FieldLayout(
                rows=[
                    LayoutRow(
                        title=gettext_noop("Details"),
                        columns=4,
                        items=[
                            LayoutItem(id="name", colspan=3),
                            LayoutItem(id="is_active"),
                            LayoutItem(id="description", colspan=4),
                        ],
                    ),
                    LayoutRow(
                        title=gettext_noop("Users"),
                        columns=3,
                        items=[
                            LayoutItem(id="assigned_groups"),
                            LayoutItem(id="assigned_users"),
                            LayoutItem(id="available_to_all"),
                            LayoutItem(id="user_filter", colspan=3),
                        ],
                    ),
                ],
            ),
        ],
        tab_configurations=[
            DetailTabsConfiguration(
                tabs=[
                    DetailTab(name=gettext_noop("Details"), url_name="tutorials_detail_overview"),
                    DetailTab(
                        name=gettext_noop("Revisions"),
                        url_name="tutorials_detail_revisions_relationship",
                    ),
                    DetailTab(name=gettext_noop("Delete"), url_name="tutorials_detail_delete"),
                ],
            ),
        ],
    ),
    model_view_settings=ModelViewSettings(
        default_dataviews=[
            TableDataView(
                name=gettext_noop("Tutorials"),
                is_default=True,
                display_fields=["name", "description"],
                sort_field="name",
            )
        ],
        dataview_actions=tutorial_dataview_actions,
    ),
    object_actions=tutorial_object_actions,
)


class Tutorial(BloomerpModel):
    """Keep a stable tutorial identity across content revisions."""

    class Meta(BloomerpModel.Meta):
        db_table = "bloomerp_tutorial"
        verbose_name = _("Tutorial")
        verbose_name_plural = _("Tutorials")

    bloomerp_config = TUTORIAL_CONFIG
    filter_lookups: ClassVar[dict[str, tuple[LookupDefinition, ...]]] = {
        "id": (STARTABLE_TUTORIAL,),
    }

    name = models.CharField(max_length=255, verbose_name=_("Name"))
    description = models.TextField(verbose_name=_("Description"))
    source_key = models.CharField(
        max_length=255,
        unique=True,
        null=True,
        blank=True,
        editable=False,
        verbose_name=_("Source key"),
        help_text=_("Namespaced key for a tutorial supplied by an installed app."),
    )
    source_retired = models.BooleanField(
        default=False, editable=False, verbose_name=_("Retired by source"),
    )
    is_active = models.BooleanField(default=True, verbose_name=_("Active"))
    available_to_all = models.BooleanField(
        default=False,
        verbose_name=_("Available to all users"),
        help_text=_("Make this tutorial available to every signed-in user."),
    )
    user_filter = models.JSONField(
        default=list,
        blank=True,
        validators=[validate_tutorial_user_filter],
        verbose_name=_("User filter"),
        help_text=_("Users in the tutorial audience must also match these conditions."),
    )
    assigned_users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="assigned_tutorials",
        verbose_name=_("Assigned users"),
    )
    assigned_groups = models.ManyToManyField(
        "auth.Group",
        blank=True,
        related_name="assigned_tutorials",
        verbose_name=_("Assigned groups"),
    )
    topics = models.ManyToManyField(
        "bloomerp.TutorialTopic",
        blank=True,
        related_name="tutorials",
        verbose_name=_("Topics"),
    )

    @classmethod
    def audience_for(
        cls, user: AbstractBaseUser | AnonymousUser
    ) -> models.QuerySet[Tutorial]:
        """Narrow the active assigned audience to filters matching this user."""
        if not user.is_authenticated or user.pk is None:
            return cls.objects.none()

        audience = cls.objects.filter(is_active=True, source_retired=False).filter(
            models.Q(available_to_all=True)
            | models.Q(assigned_users=user)
            | models.Q(assigned_groups__in=user.groups.all())
        )
        user_model = get_user_model()
        learner = user_model._base_manager.filter(pk=user.pk)
        manager = ModelFilterManager(user_model)
        matches = models.Q(user_filter=[])
        configured = (
            audience.exclude(user_filter=[])
            .order_by()
            .values_list("pk", "user_filter")
            .distinct()
        )
        for tutorial_id, stored_filter in configured:
            try:
                filters = parse_tutorial_user_filter(stored_filter)
                matching_user = manager.apply(filters, queryset=learner)
            except (FieldError, ValidationError):
                continue
            matches |= models.Q(pk=tutorial_id, user_filter=stored_filter) & models.Q(
                models.Exists(matching_user)
            )
        return audience.filter(matches).distinct()

    def get_export_data(self, permissions: UserPolicyManager) -> dict[str, Any]:
        """Serialize portable tutorial fields after checking read access to every record."""
        view = BloomerpPermission.VIEW
        if not permissions.has_access_to_object(
            self, view, fields=list(TUTORIAL_EXPORT_FIELDS),
        ):
            raise PermissionDenied()

        tutorial = {field: getattr(self, field) for field in TUTORIAL_EXPORT_FIELDS}
        if permissions.has_access_to_object(self, view, fields=["topics"]):
            tutorial["topics"] = [
                topic.source_key
                for topic in self.topics.exclude(source_key__isnull=True).exclude(source_key="")
                if permissions.has_access_to_object(topic, view, fields=["source_key"])
            ]
        revisions = []
        for revision in self.revisions.order_by("number").prefetch_related("steps"):
            if not permissions.has_access_to_object(
                revision, view, fields=list(REVISION_EXPORT_FIELDS),
            ):
                raise PermissionDenied()
            revision_data = {field: getattr(revision, field) for field in REVISION_EXPORT_FIELDS}
            revision_data["published_at"] = (
                revision.published_at.isoformat() if revision.published_at else None
            )
            steps = []
            for step in revision.steps.all():
                if not permissions.has_access_to_object(
                    step, view, fields=list(STEP_EXPORT_FIELDS),
                ):
                    raise PermissionDenied()
                steps.append({field: getattr(step, field) for field in STEP_EXPORT_FIELDS})
            revision_data["steps"] = steps
            revisions.append(revision_data)

        return {"schema_version": TUTORIAL_YAML_VERSION, "tutorial": {**tutorial, "revisions": revisions}}

    def can_create_revision(self, user: AbstractBaseUser | AnonymousUser) -> bool:
        """Require access to edit this tutorial and permission to add revisions."""
        from bloomerp.permissions.manager import UserPolicyManager

        if not user.is_authenticated:
            return False
        permissions = UserPolicyManager(user)
        return permissions.has_global_permission(
            TutorialRevision, BloomerpPermission.ADD
        ) and permissions.has_access_to_object(
            self,
            [BloomerpPermission.VIEW, BloomerpPermission.CHANGE],
            match=PermissionMatch.ALL,
        )

    def __str__(self) -> str:
        """Return the tutorial's display name."""
        return self.name
