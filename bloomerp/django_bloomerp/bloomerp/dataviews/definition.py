
from __future__ import annotations

from dataclasses import dataclass, field
from types import UnionType
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    ClassVar,
    Literal,
    Type,
    Union,
    get_args,
    get_origin,
)

from django import forms
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db import models
from django.db.models import QuerySet
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils.translation import gettext_lazy as _
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.fields import FieldInfo

if TYPE_CHECKING:
    from django.contrib.contenttypes.models import ContentType
    from django.db.models import Model, QuerySet
    from django.http import HttpRequest

    from bloomerp.filters.definition import Filters
    from bloomerp.models.application_field import ApplicationField
    from bloomerp.models.definition import ObjectAction
    from bloomerp.models.users.user_list_view_preference import UserListViewPreference
    from bloomerp.services.user_services import DataViewFields


@dataclass
class DataviewState:
    """Canonical request, query, and rendering state for a dataview."""

    request: HttpRequest
    content_type: ContentType
    model: type[Model]
    preference: UserListViewPreference
    queryset: QuerySet
    fields: DataViewFields
    render_fields: list[ApplicationField]
    avatar_field: ApplicationField | None
    options: Any | None = None
    query: str | None = None
    count: int = 0
    filters: Filters | None = None
    operation_context_token: str | None = None
    object_actions: list[ObjectAction] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)

    @property
    def content_type_id(self) -> int:
        return self.content_type.id

    @property
    def accessible_fields(self) -> list[ApplicationField]:
        return [field for field, _is_visible in self.fields.accessible_fields]


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

    def __init__(self, state: DataviewState):
        self.state = state
        self.options = state.options

    @property
    def definition_key(self) -> str:
        return self.state.preference.view_type

    @classmethod
    def get_reserved_query_params(cls) -> set[str]:
        return set(cls.reserved_query_params)

    @classmethod
    def apply_sorting(cls, queryset, _request, _data_view_fields, _options: object | None = None):
        return queryset, {}

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
    def get_field_from_data_view_fields(dataview_fields, field_name):
        if field_name in (None, ""):
            return None

        for field, _is_visible in getattr(dataview_fields, "accessible_fields", []):
            if field.field == field_name:
                return field

        for field in getattr(dataview_fields, "visible_fields", []):
            if field.field == field_name:
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
        context = dict(self.state.context)
        context.update({
            "content_type_id": self.state.content_type_id,
            "queryset": pagination.queryset,
            "fields": self.state.render_fields,
            "avatar_field": self.state.avatar_field,
            "preference": self.state.preference,
            "object_actions": self.state.object_actions,
        })
        return context

    def render(
        self,
        pagination: DataviewPagination,
        *,
        extra_context: dict[str, Any] | None = None,
    ) -> str:
        if not self.template_name:
            raise NotImplementedError("Dataview renderers must define template_name.")

        context = self.get_context_data(pagination)
        context.update(extra_context or {})

        return render_to_string(
            self.template_name,
            context,
            request=self.state.request,
        )


class BaseDataview(BaseModel):
    """Shared declarative settings for a default model dataview."""

    model_config = ConfigDict(extra="forbid")

    application_field_options: ClassVar[
        dict[str, Literal["single", "multiple"]]
    ] = {}

    name: str = Field(default="Default", min_length=1, max_length=255)
    is_default: bool = True
    display_fields: list[str] = Field(default_factory=list)
    default_filters: dict[str, str | list[str]] = Field(default_factory=dict)
    split_view_enabled: bool = False

    @classmethod
    def option_field_names(cls) -> list[str]:
        """Return config fields persisted in ``UserListViewPreference.options``."""
        common_fields = set(BaseDataview.model_fields)
        return [
            name
            for name in cls.model_fields
            if name not in common_fields and name != "view_type"
        ]

    def dump_options(self) -> dict[str, Any]:
        """Serialize only view-specific preference options."""
        return self.model_dump(
            include=set(self.option_field_names()),
            mode="json",
        )

    def resolve_options(
        self,
        resolve_field_name: Callable[[str | None], str | None],
    ) -> dict[str, Any]:
        """Resolve declarative field names into persisted dataview options.

        Dataviews with options that reference ``ApplicationField`` names declare
        those options in ``application_field_options``. Other options are
        serialized unchanged. Subclasses may override this method when their
        persisted option format needs custom resolution.
        """
        options = self.dump_options()
        for option_name, cardinality in self.application_field_options.items():
            value = options.get(option_name)
            if cardinality == "single":
                options[option_name] = resolve_field_name(value)
                continue
            if cardinality == "multiple":
                options[option_name] = [
                    resolved
                    for field_name in value or []
                    if (resolved := resolve_field_name(field_name)) is not None
                ]
                continue
            raise ValueError(
                f"Unsupported application field option cardinality {cardinality!r}."
            )
        return options

    @classmethod
    def form_factory(
        cls,
        state: DataviewState,
    ) -> type[forms.Form]:
        """Create the options form class for this dataview configuration."""
        form_fields = {
            name: cls.create_form_field(
                name,
                cls.model_fields[name],
                state,
            )
            for name in cls.option_field_names()
        }
        for form_field in form_fields.values():
            if isinstance(form_field.widget, forms.Select):
                form_field.widget.attrs.setdefault(
                    "class",
                    "select select-sm w-40 bg-base border-0",
                )
        return type(f"{cls.__name__}OptionsForm", (forms.Form,), form_fields)

    @classmethod
    def create_form_field(
        cls,
        name: str,
        field_info: FieldInfo,
        _state: DataviewState,
    ) -> forms.Field:
        """Create a sensible default Django field for one Pydantic option."""
        annotation = field_info.annotation
        origin = get_origin(annotation)
        args = get_args(annotation)
        non_none_args = tuple(arg for arg in args if arg is not type(None))
        required = field_info.is_required()
        label = field_info.title or name.replace("_", " ").title()
        help_text = field_info.description or ""

        if origin in {Union, UnionType} and len(non_none_args) == 1:
            annotation = non_none_args[0]
            origin = get_origin(annotation)
            args = get_args(annotation)
            required = False

        if origin is Literal:
            values = list(args)
            value_type = type(values[0]) if values else str
            return forms.TypedChoiceField(
                label=label,
                help_text=help_text,
                required=required,
                choices=[(value, str(value).replace("_", " ").title()) for value in values],
                coerce=value_type,
            )
        if annotation is bool:
            return forms.BooleanField(
                label=label,
                help_text=help_text,
                required=False,
            )
        if origin is list:
            return forms.MultipleChoiceField(
                label=label,
                help_text=help_text,
                required=required,
                choices=[],
            )
        if origin is dict:
            return forms.JSONField(
                label=label,
                help_text=help_text,
                required=required,
            )
        if annotation is int:
            return forms.IntegerField(
                label=label,
                help_text=help_text,
                required=required,
            )
        return forms.CharField(
            label=label,
            help_text=help_text,
            required=required,
        )

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
        choices.append((application_field.field, application_field.title))

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
class DataviewTypeDefinition:
    """Metadata, configuration, and renderer wiring for one dataview type."""

    key: str
    label: str
    description: str
    icon: str
    renderer_cls: type[BaseDataviewRenderer]
    config_cls: type[BaseDataview]
    requires_display_fields: bool = True
    available_for_model: Callable[[Type[models.Model]], bool] = lambda model: True
