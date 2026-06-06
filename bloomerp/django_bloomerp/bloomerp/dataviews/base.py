
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.forms import Form
from django.http import HttpResponse
from django.template.loader import render_to_string

if TYPE_CHECKING:
    from django.contrib.contenttypes.models import ContentType
    from django.db.models import Model, QuerySet
    from django.http import HttpRequest

    from bloomerp.models import ApplicationField
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


@dataclass
class DataviewTypeDefinition:
    """Static metadata and capabilities for one dataview type."""

    key: str
    label: str
    description: str
    icon: str
    renderer_cls: type["BaseDataviewRenderer"]
    supports_display_fields: bool = True
    supports_split_view: bool = True


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
    def get_field_from_data_view_fields(data_view_fields, field_id):
        if field_id in (None, ""):
            return None

        try:
            field_id = int(field_id)
        except (TypeError, ValueError):
            return None

        for field, _is_visible in getattr(data_view_fields, "accessible_fields", []):
            if field.id == field_id:
                return field

        for field in getattr(data_view_fields, "visible_fields", []):
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
