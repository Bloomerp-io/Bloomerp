import json
import inspect
from typing import Any, Callable, Literal, Optional, Type

from django.http import HttpRequest, HttpResponse
from bloomerp.config.definition import BloomerpConfig
from bloomerp.field_types.lookups import Lookup
from bloomerp.workspaces.base import BaseTileConfig
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializeAsAny,
    field_validator,
    model_validator,
)
from django.conf import settings
from django.db.models import Model

class LayoutItem(BaseModel):
    id: int | str
    colspan: int = 1
    config: dict = Field(default_factory=dict)

    icon: str | None = None
    label: Optional[str] = None
    is_visible: bool = True
    content: Optional[str] = None
    component_name: Optional[str] = None
    border: bool = False
    edit_url: Optional[str] = None
    search_keywords: Optional[str] = None
    extra_attrs: Optional[dict] = Field(default_factory=dict)

    @property
    def config_json(self) -> str:
        return json.dumps(self.config)

    def set_content(self, content: str):
        self.content = content


class LayoutRow(BaseModel):
    columns: int
    items: list[LayoutItem] = Field(default_factory=list)
    title: Optional[str] = None


class BaseLayout(BaseModel):
    """Base layout class for defining layouts in Bloomerp.

    This class serves as a base for other layout classes, providing common
    attributes and methods that can be extended or overridden by subclasses.
    """

    name: str = "Default"
    is_default: bool = True
    rows: list[LayoutRow] = Field(default_factory=list)


class FieldLayout(BaseLayout):
    pass

class WorkspaceLayout(BaseLayout):
    pass


def validate_declarative_tile_configs(
    tiles: list[BaseTileConfig],
    *,
    owner: str,
) -> list[BaseTileConfig]:
    """Require stable, unique IDs for tiles declared in configuration."""
    seen_ids: set[str] = set()
    for tile in tiles:
        tile_id = (tile.id or "").strip()
        if not tile_id:
            raise ValueError(f"Every tile declared on {owner} must have an id.")
        if tile_id in seen_ids:
            raise ValueError(f"Duplicate tile id '{tile_id}' declared on {owner}.")
        tile.id = tile_id
        seen_ids.add(tile_id)
    return tiles

class ApiFilterRule(BaseModel):
    field: str
    operator: str = Lookup.EQUALS.value.id
    value: str | int | float | bool | None = None

    def get_lookup_operator(self) -> str:
        operator_value = str(self.operator or "").strip()
        for lookup in Lookup:
            if operator_value == lookup.value.id:
                return lookup.value.django_representation or operator_value
        return operator_value

class PublicAccessRule(BaseModel):
    """A public access rule defines in which cases objects can be accessed via the
    auto generated API without authentication.

    For example, we might want to expose a `BlogPost` model publicly so that
    anonymous users can list and read published posts, while drafts remain
    private. That would look something like this:
    ```python
    rule = PublicAccessRule(
        field_actions={
            "title": ["list", "read"],
            "slug": ["list", "read"],
            "summary": ["list", "read"],
            "content": ["read"],
        },
        row_actions=["list", "read"],
        filters=[
            ApiFilterRule(
                field="status",
                operator="equals",
                value="published",
            )
        ],
    )
    ```
    In the above case, anonymous users are able to list and read blog posts
    whose `status == "published"`, while only the configured fields are exposed
    for each action.

    In the case that we want to expose a narrower public listing than the public
    detail view, that would look something like this:
    ```python
    rule = PublicAccessRule(
        field_actions={
            "title": ["list", "read"],
            "slug": ["list", "read"],
            "summary": ["list"],
            "content": ["read"],
        },
        row_actions=["list", "read"],
        filters=[
            ApiFilterRule(
                field="is_archived",
                operator="not_equals",
                value=True,
            )
        ],
    )
    ```
    In the above case, anonymous users can still list and read the object, but
    the list response is limited to `title`, `slug`, and `summary`, while the
    read response can additionally include `content`. The filter ensures that
    archived objects stay out of the public API.
    """
    row_actions: list[Literal["list", "read"]] = Field(
        default_factory=lambda: ["list", "read"]
    )
    field_actions: dict[str | Literal["__all__"], list[Literal["list", "read"]] | Literal["__all__"]] = Field(
        default_factory=lambda: {"__all__": "__all__"}
    )
    filters: list[ApiFilterRule] = Field(default_factory=list)

    def get_row_actions(self) -> list[str]:
        return list(self.row_actions)

    def get_accessible_fields(self, action: str) -> set[str] | None:
        normalized_action = str(action or "").strip().lower()
        wildcard_actions = self.field_actions.get("__all__")
        if wildcard_actions == "__all__" or (
            isinstance(wildcard_actions, list) and normalized_action in wildcard_actions
        ):
            return None

        allowed_fields: set[str] = set()
        for field_name, actions in self.field_actions.items():
            if field_name == "__all__":
                continue
            if actions == "__all__" or (
                isinstance(actions, list) and normalized_action in actions
            ):
                allowed_fields.add(field_name)
        return allowed_fields

class UserAccessRule(BaseModel):
    """A user access rule defines in which cases users can access an object via the api. The through field serves as the entry point for the user access definition. Note that user access rules only apply to the auto generated API's.

    The special value `Self` can be used as a wildcard when the object being
    accessed is the authenticated user itself. In that case, the rule matches
    when `object.pk == request.user.pk`.

    For example, we might want to give API access to a `Project` model so that users can create particular and manage particular projects of their own, whilst the integrity of other people's projects stay the same. That would look something like this:
    ```python
    rule = UserAccessRule(
        through_field="owner",
        field_actions={
            "name" : ["view", "change", "add"],
            "type: ["view", "change", "add"],
            "datetime_created" : ["view"],
            "datetime_updated" : ["view"],
        },
        row_actions=["view", "add", "change", "delete"]
    )
    ```
    In above case, the user is able to create, add, change, delete, and view objects (as defined in the row actions) with the condition that project.owner == user

    In the case that we want to give user access to objects with a deeper link to a user, that would look something like this (assume the model `ProjectTask`). 
    ```python
    rule = UserAccessRule(
        through_field="project.owner",
        field_actions={
            "name" : ["view", "change", "add"],
            "content: ["view", "change", "add"],
            "datetime_created" : ["view"],
            "datetime_updated" : ["view"],
        },
        row_actions=["view", "add", "change", "delete"]
    )
    ```
    In the below case, the user is only able to create, view, add, and change objects (as defined in the row actions) with the condition of project_task.project.owner == user

    For the `User` model itself, that would look like:
    ```python
    rule = UserAccessRule(
        through_field="Self",
        field_actions={
            "avatar": ["view", "change"],
            "has_seen_tutorial": ["view", "change"],
        },
        row_actions=["view", "change", "delete"],
    )
    ```
    In that case, the authenticated user can only access their own user record
    via the generated API.

    """
    through_field: str
    field_actions:dict[str|Literal['__all__'], list[Literal["view", "change", "add", "delete"]] | Literal['__all__']]
    row_actions:list[Literal["view", "change", "add", "delete"]]
    filters:list[ApiFilterRule] = Field(default_factory=list)

class ApiNesting(BaseModel):
    for_field: str
    fields: list[str | Literal["__all__"]] = Field(default_factory=lambda: ["__all__"])
    on_action: list[Literal["list", "read"]] = Field(
        default_factory=lambda: ["list", "read"]
    )
    auto_pk: bool = True

    def get_accessible_fields(self, action: str) -> set[str] | None:
        normalized_action = str(action or "").strip().lower()
        if normalized_action not in self.on_action:
            return set()

        if "__all__" in self.fields:
            return None

        return {
            field_name
            for field_name in self.fields
            if field_name != "__all__"
        }

class ApiSettings(BaseModel):
    """
    Configures how Bloomerp API's are set up.

    Settings are:
        - enable_auto_generation: defines whether API endpoints are autogenerated for this model. Defaults to False
        - public_access: defines read/list exceptions for public API access
        - user_access: defines exceptions for public API access
        - public_access_for_authenticated_fallback: whether there should be a fallback to potential public access if the user can't/fails to authenticate
    """

    enable_auto_generation: bool = False
    public_access: list[PublicAccessRule] = Field(default_factory=list)
    user_access:list[UserAccessRule] = Field(default_factory=list)
    nesting: list[ApiNesting] = Field(default_factory=list)
    public_access_for_authenticated_fallback: bool = True

    def get_public_access_rules(self, action: str) -> list[PublicAccessRule]:
        normalized_action = str(action or "").strip().lower()
        return [
            rule
            for rule in self.public_access
            if normalized_action in rule.get_row_actions()
        ]

    def get_user_access_rules(self, action: str) -> list[UserAccessRule]:
        normalized_action = str(action or "").strip().lower()
        return [
            rule
            for rule in self.user_access
            if normalized_action in rule.row_actions
        ]

    def has_public_access(self) -> bool:
        return len(self.public_access) > 0

    def has_user_access(self) -> bool:
        return len(self.user_access) > 0

    def get_nesting_rules(self, action: str) -> list[ApiNesting]:
        normalized_action = str(action or "").strip().lower()
        return [
            rule
            for rule in self.nesting
            if normalized_action in rule.on_action
        ]

class ObjectHTML(BaseModel):
    template_name:str
    
    should_render_func:Callable[[HttpRequest, Model], bool] = lambda req, obj : True

class ObjectAction(BaseModel):
    id:str
    
    label:str
    
    execution_func:Callable[[HttpRequest, Model], HttpResponse]
    
    should_render_func:Callable[[HttpRequest, Model], bool] = lambda req, obj : True
    
    icon:Optional[str] = None
    
    style:Literal["primary", "secondary"] = "secondary"
    
    success_message:Optional[str] = None
    
class ObjectModalAction(BaseModel):
    id:str
    
    label:str
    
    endpoint:Callable[[Model], str]
    
    icon:Optional[str] = None
    
    style:Literal["primary", "secondary"] = "secondary"
    
    should_render_func:Callable[[HttpRequest, Model], bool] = lambda req, obj : True
    
    modal_title:Optional[str] = ""

    modal_size:Literal["sm", "md", "lg", "xl", "full"] = "md"

class DetailViewSettings(BaseModel):
    """
    Settings regarding detail views for certain models
    """
    skip_views : Optional[list[str]] = None


class BaseDataView(BaseModel):
    """Shared declarative settings for a default model data view."""

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


class TableDataView(BaseDataView):
    """A declarative table data view."""

    view_type: Literal["table"] = "table"
    page_size: Literal[10, 25, 50, 100] = 25
    sort_field: str | None = None
    sort_direction: Literal["asc", "desc"] = "asc"


class KanbanDataView(BaseDataView):
    """A declarative Kanban data view."""

    view_type: Literal["kanban"] = "kanban"
    group_by_field: str | None = None
    page_size: Literal[10, 25, 50, 100] = 25
    sort_field: str | None = None
    sort_direction: Literal["asc", "desc"] = "asc"


class CardDataView(BaseDataView):
    """A declarative card data view."""

    view_type: Literal["card"] = "card"
    page_size: Literal[10, 25, 50, 100] = 25


class CalendarDataView(BaseDataView):
    """A declarative calendar data view."""

    view_type: Literal["calendar"] = "calendar"
    start_field: str | None = None
    end_field: str | None = None
    view_mode: Literal["day", "week", "month", "year", "list"] = "week"
    color_grouping_field: str | None = None


class GanttDataView(BaseDataView):
    """A declarative Gantt data view."""

    view_type: Literal["gant"] = "gant"
    start_field: str
    end_field: str
    dependency_from_field: str | None = None
    dependency_for_field: str | None = None
    page_size: Literal[10, 25, 50, 100] = 25


class PivotTableDataView(BaseDataView):
    """A declarative pivot-table data view."""

    view_type: Literal["pivot_table"] = "pivot_table"
    row_fields: list[str] = Field(default_factory=list)
    column_fields: list[str] = Field(default_factory=list)
    value_fields: list[str] = Field(default_factory=list)
    aggregation: Literal["count", "sum", "min", "max", "avg"] = "count"
    show_row_totals: bool = True
    show_column_totals: bool = True
    totals_scope: Literal["page", "dataset"] = "page"
    page_size: Literal[10, 25, 50, 100] = 25


DefaultDataView = (
    TableDataView
    | KanbanDataView
    | CardDataView
    | CalendarDataView
    | GanttDataView
    | PivotTableDataView
)


class ModelViewSettings(BaseModel):
    """Optional settings for a model's collection views."""

    skip_views: Optional[list[str]] = None
    default_dataviews: list[DefaultDataView] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_default_dataviews(self):
        """Require unique names and one selected setup when defaults exist."""
        if not self.default_dataviews:
            return self

        names = [data_view.name for data_view in self.default_dataviews]
        if len(names) != len(set(names)):
            raise ValueError("Default data view names must be unique.")

        default_count = sum(
            data_view.is_default for data_view in self.default_dataviews
        )
        if default_count != 1:
            raise ValueError(
                "Exactly one configured data view must have is_default=True."
            )
        return self


class BloomerpModelConfig(BaseModel):
    """
    Used to define certain bloomerp related meta data on a model. 

    Settings are:
        - module: the canonical module to which this model belongs.
        - layout: a layout object defining how the default CRUD layout for users is.
        - tiles: reusable tile configurations associated with this model.
        - string_search_fields: optional field paths used by the shared string search service.

    Usage
    ```python
    from bloomerp.models.definition import BloomerpModelConfig

    class Lorum(BloomerpModel):
        bloomerp_config = BloomerpModelConfig(
            ...
        )
    ``` 
    """

    module: str | type | None = None

    layout: Optional[FieldLayout] = None

    tiles: list[SerializeAsAny[BaseTileConfig]] = Field(default_factory=list)

    allow_string_search: bool = True

    string_search_fields: list[str] | None = None

    is_internal: bool = False

    api_settings: Optional[ApiSettings] = None

    record_activity_log : bool = True
    
    create_redirect_url_func : Optional[Callable[[Model], str]] = None
    
    detail_view_settings : Optional[DetailViewSettings] = None
    
    model_view_settings : Optional[ModelViewSettings] = None 
    
    object_actions : Optional[list[ObjectAction | ObjectHTML | ObjectModalAction]] = None

    @field_validator("tiles")
    @classmethod
    def validate_tiles(
        cls,
        value: list[BaseTileConfig],
    ) -> list[BaseTileConfig]:
        return validate_declarative_tile_configs(
            value,
            owner=cls.__name__,
        )
    
    
    
    @field_validator("module", mode="before")
    @classmethod
    def normalize_module(cls, value: Any) -> str | None:
        if value in (None, ""):
            return None

        if isinstance(value, str):
            return value

        try:
            from bloomerp.modules.definition import BloomerpModule, ModuleConfig
        except Exception:
            return value

        if isinstance(value, ModuleConfig):
            return value.full_id or value.id

        if inspect.isclass(value):
            if issubclass(value, ModuleConfig):
                module = value()
                return module.full_id or module.id

            if issubclass(value, BloomerpModule):
                module = value.to_config()
                return module.full_id or module.id

        return value

    def get_public_access_rules(self, action: str) -> list[PublicAccessRule]:
        if self.api_settings is None:
            return []
        return self.api_settings.get_public_access_rules(action)

    def has_public_access(self) -> bool:
        if self.api_settings is None:
            return False
        return self.api_settings.has_public_access()

    def get_user_access_rules(self, action: str) -> list[UserAccessRule]:
        if self.api_settings is None:
            return []
        return self.api_settings.get_user_access_rules(action)

    def has_user_access(self) -> bool:
        if self.api_settings is None:
            return False
        return self.api_settings.has_user_access()

    def get_nesting_rules(self, action: str):
        if self.api_settings is None:
            return []
        return self.api_settings.get_nesting_rules(action)

    def should_enable_api_auto_generation(self) -> bool:
        bloomerp_config : BloomerpConfig = getattr(settings, "BLOOMERP_CONFIG")

        if self.api_settings is None:
            # In this case, use the global setting to determine whether to auto generate API endpoints
            return bloomerp_config.auto_generate_api_endpoints
        
        return self.api_settings.enable_auto_generation


def get_model_config(model_or_object:Type[Model]|Model) -> BloomerpModelConfig | None:
    """Returns the bloomerp model config for a model or object (if it exists)

    Args:
        model_or_object (Type[Model] | Model): the model or object

    Returns:
        BloomerpModelConfig | None: the config object
    """
    # Get the model class from either a model class or an instance
    model_class = model_or_object if inspect.isclass(model_or_object) else type(model_or_object)
    
    # Check if the model has a bloomerp_config attribute
    if hasattr(model_class, 'bloomerp_config'):
        config = getattr(model_class, 'bloomerp_config')
        if isinstance(config, BloomerpModelConfig):
            return config
    
    return None
    
