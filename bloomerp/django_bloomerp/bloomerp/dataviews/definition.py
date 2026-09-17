
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Type

from django import forms
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db import models
from django.db.models import QuerySet
from django.forms import Form
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils.translation import gettext_lazy as _
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator

if TYPE_CHECKING:
    from django.contrib.contenttypes.models import ContentType
    from django.db.models import Model, QuerySet
    from django.http import HttpRequest

    from bloomerp.models.application_field import ApplicationField
    from bloomerp.models.definition import ObjectAction
    from bloomerp.models.users.user_list_view_preference import UserListViewPreference


@dataclass
class DataviewRenderState:
    """Shared state passed from the dataview shell to a concrete renderer."""

    request: HttpRequest
    content_type_id: int
    content_type: ContentType
    model: type[Model]
    preference: UserListViewPreference
    queryset: QuerySet
    fields: Any
    render_fields: list[ApplicationField]
    avatar_field: ApplicationField | None
    options: Any | None = None
    object_actions: list[ObjectAction] = field(default_factory=list)
    extra_context: dict[str, Any] = field(default_factory=dict)


@dataclass
class DataviewPagination:
    """Pagination state returned by a dataview renderer."""

    queryset: Any
    page_obj: Any | None = None
    pagination_pages: list[int | None] = field(default_factory=list)
    show_global_pagination: bool = False


class BaseDataviewRenderer:
    """Base renderer for the inner dataview body."""

    template_name: str = ""
    reserved_query_params: set[str] = set()

    def __init__(self, state: DataviewRenderState):
        self.state = state
        self.options = state.options

    @property
    def definition_key(self) -> str:
        return self.state.preference.view_type

    @classmethod
    def get_options_form(cls, *, state: DataviewRenderState) -> type[Form] | None:
        return None

    def apply_queryset(self):
        return self.state.queryset

    @classmethod
    def get_reserved_query_params(cls) -> set[str]:
        return set(cls.reserved_query_params)

    @classmethod
    def apply_sorting(cls, queryset, _request, _data_view_fields, _options: object | None = None):
        return queryset, {}

    def paginate(self, queryset) -> DataviewPagination:
        return DataviewPagination(queryset=queryset)

    @classmethod
    def paginate_queryset(
        cls,
        queryset,
        _preference,
        _request,
        _options: object | None = None,
    ) -> DataviewPagination:
        return DataviewPagination(queryset=queryset)

    @classmethod
    def handle_action(cls, action: str, _request, _state) -> HttpResponse:
        return HttpResponse(f"Unsupported dataview action: {action}", status=400)

    @staticmethod
    def get_field_from_data_view_fields(dataview_fields, field_id):
        if field_id in (None, ""):
            return None

        try:
            field_id = int(field_id)
        except (TypeError, ValueError):
            return None

        for field, _is_visible in getattr(dataview_fields, "accessible_fields", []):
            if field.id == field_id:
                return field

        for field in getattr(dataview_fields, "visible_fields", []):
            if field.id == field_id:
                return field

        return None

    @staticmethod
    def paginate_object_list(object_list, page_size: int, page_number):
        paginator = Paginator(object_list, page_size)

        try:
            return paginator.page(page_number)
        except PageNotAnInteger:
            return paginator.page(1)
        except EmptyPage:
            return paginator.page(paginator.num_pages or 1)

    @staticmethod
    def build_pagination_range(page_obj, window: int = 2) -> list[int | None]:
        paginator = page_obj.paginator
        total_pages = paginator.num_pages
        current_page = page_obj.number

        if total_pages <= 1:
            return [1]

        pages: list[int | None] = []

        def add_page(page_number: int) -> None:
            pages.append(page_number)

        def add_ellipsis() -> None:
            if pages and pages[-1] is not None:
                pages.append(None)

        add_page(1)

        start = max(2, current_page - window)
        end = min(total_pages - 1, current_page + window)

        if start > 2:
            add_ellipsis()

        for page_number in range(start, end + 1):
            add_page(page_number)

        if end < total_pages - 1:
            add_ellipsis()

        add_page(total_pages)

        return pages

    @staticmethod
    def build_querystring(request, remove: set[str] | tuple[str, ...] | list[str]) -> str:
        querystring = request.GET.copy()
        for key in remove:
            querystring.pop(key, None)
        return querystring.urlencode()

    def get_context_data(self, pagination: DataviewPagination) -> dict[str, Any]:
        context = dict(self.state.extra_context)
        context.update({
            "content_type_id": self.state.content_type_id,
            "queryset": pagination.queryset,
            "fields": self.state.render_fields,
            "avatar_field": self.state.avatar_field,
            "preference": self.state.preference,
            "object_actions": self.state.object_actions,
        })
        return context

    def render(self, pagination: DataviewPagination | None = None) -> str:
        if not self.template_name:
            raise NotImplementedError("Dataview renderers must define template_name.")

        if pagination is None:
            pagination = self.paginate(self.apply_queryset())

        return render_to_string(
            self.template_name,
            self.get_context_data(pagination),
            request=self.state.request,
        )


class BaseDataView(BaseModel):
    """Shared declarative settings for a default model dataview."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="Default", min_length=1, max_length=255)
    is_default: bool = True
    display_fields: list[str] = Field(default_factory=list)
    default_filters: dict[str, str | list[str]] = Field(default_factory=dict)
    split_view_enabled: bool = False

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        """Normalize the user-facing preference name."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("Name is required.")
        return normalized

    @field_validator("display_fields")
    @classmethod
    def normalize_display_fields(cls, value: list[str]) -> list[str]:
        """Normalize field names and reject duplicates."""
        normalized = [field_name.strip() for field_name in value]
        if any(not field_name for field_name in normalized):
            raise ValueError("Display field names cannot be empty.")
        if len(normalized) != len(set(normalized)):
            raise ValueError("Display field names must be unique.")
        return normalized

    @field_validator("default_filters")
    @classmethod
    def normalize_default_filters(
        cls,
        value: dict[str, str | list[str]],
    ) -> dict[str, str | list[str]]:
        """Normalize declarative filter query keys."""
        normalized: dict[str, str | list[str]] = {}
        for key, filter_value in value.items():
            normalized_key = key.strip()
            if not normalized_key:
                raise ValueError("Default filter keys cannot be empty.")
            normalized[normalized_key] = filter_value
        return normalized


class PageSize(models.IntegerChoices):
    SIZE_10 = 10, _("10")
    SIZE_25 = 25, _("25")
    SIZE_50 = 50, _("50")
    SIZE_100 = 100, _("100")


DEFAULT_OPTION_UNSET = object()


def application_field_choices(
    application_fields: QuerySet[ApplicationField],
    *,
    include_empty: bool = False,
    empty_label: str = _("None"),
    field_types: set[str] | None = None,
) -> list[tuple[str, str]]:
    choices = [("", empty_label)] if include_empty else []

    for application_field in application_fields:
        if field_types and application_field.field_type not in field_types:
            continue
        choices.append((str(application_field.id), application_field.title))

    return choices


def application_field_name_choices(
    application_fields: QuerySet[ApplicationField],
    *,
    include_empty: bool = False,
    empty_label: str = _("None"),
    field_types: set[str] | None = None,
) -> list[tuple[str, str]]:
    choices = [("", empty_label)] if include_empty else []

    for application_field in application_fields:
        if field_types and application_field.field_type not in field_types:
            continue
        choices.append((application_field.field, application_field.title))

    return choices


def page_size_choices(
    _application_fields: QuerySet[ApplicationField],
) -> dict[str, Any]:
    return {
        "choices": PageSize.choices,
        "coerce": int,
    }


@dataclass
class PreferenceOption:
    key: str
    label: str
    field_cls: type[forms.Field]
    field_attrs_func: Callable[[QuerySet[ApplicationField]], dict] | None = None
    description: str | None = None
    data_type: type = str
    default_value: Any = DEFAULT_OPTION_UNSET
    required: bool = False


@dataclass
class DataviewTypeDefinition:
    """Metadata, configuration, and renderer wiring for one dataview type."""

    key: str
    label: str
    description: str
    icon: str
    renderer_cls: type[BaseDataviewRenderer]
    config_cls: type[BaseDataView]
    opts: list[PreferenceOption] = field(default_factory=list)
    requires_display_fields: bool = True
    model: type[BaseModel] | None = None
    available_for_model:Callable[[Type[models.Model]], bool] = lambda model: True

    def create_opts_form(
        self,
        application_fields: QuerySet[ApplicationField],
    ) -> type[forms.Form]:
        """Creates an opts form based on the opts.

        Returns:
            forms.Form: the form
        """
        attrs = {}
        for option in self.opts:

            # Get the extra opts
            extra_opts = {}
            if option.field_attrs_func:
                extra_opts = option.field_attrs_func(application_fields)

            attrs[option.key] = option.field_cls(
                label=option.label,
                help_text=option.description,
                required=option.required,
                **extra_opts,
            )
            attrs[option.key].widget.attrs.setdefault(
                "class",
                "select select-sm w-40 bg-base border-0",
            )

        return type("OptionsForm", (forms.Form,), attrs)

    def create_model_from_opts(self) -> type[BaseModel]:
        attrs = {}
        for opt in self.opts:
            if opt.default_value is not DEFAULT_OPTION_UNSET:
                model_field = (opt.data_type, opt.default_value)
            else:
                model_field = (opt.data_type, ...)

            attrs[opt.key] = model_field
        model_name = "".join(part.title() for part in self.key.split("_"))
        return create_model(f"{model_name}DataviewOptions", **attrs)

    def get_options_model(self) -> type[BaseModel]:
        return self.model or self.create_model_from_opts()
