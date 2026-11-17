import inspect
import json
import re
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import TYPE_CHECKING, Any, Literal, Optional, Self, Type
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.contenttypes.models import ContentType
from django.db.models import Model, QuerySet
from django.http import HttpRequest, HttpResponse, StreamingHttpResponse
from django.utils.translation import gettext
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializeAsAny,
    field_validator,
    model_validator,
)

from bloomerp.config.definition import BloomerpConfig
from bloomerp.dataviews.definition import BaseDataview
from bloomerp.filters.definition import Filters
from bloomerp.models.object_actions.defaults import get_default_object_actions
from bloomerp.permissions.definition import AccessRule, BloomerpPermission
from bloomerp.workspaces.base import BaseTileConfig

if TYPE_CHECKING:
    from bloomerp.models.audit.activity_log import ActivityLogAction


class LayoutItem(BaseModel):
    id: int | str
    colspan: int = 1
    config: dict = Field(default_factory=dict)

    icon: str | None = None
    label: Optional[str] = None
    help_text: str | None = None
    is_visible: bool = True
    content: Optional[str] = None
    component_name: Optional[str] = None
    border: bool = False
    edit_url: Optional[str] = None
    search_keywords: Optional[str] = None
    extra_attrs: Optional[dict] = Field(default_factory=dict)
    label_content_right: Optional[str] = None

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


# ----------------------------------
# DETAIL TABS CONFIGURATION
# ----------------------------------
DETAIL_TAB_TEMPLATE_ARGUMENT = re.compile(r"{{\s*([^{}]+?)\s*}}")


def validate_detail_tab_url(url: str) -> str:
    """Validate and normalize a declarative detail-tab URL template."""
    normalized = url.strip()
    if not normalized:
        raise ValueError("URL is required.")

    arguments = {
        argument.strip()
        for argument in DETAIL_TAB_TEMPLATE_ARGUMENT.findall(normalized)
    }
    if arguments - {"pk"}:
        raise ValueError("Only the {{pk}} placeholder is supported.")

    parsed = urlsplit(normalized)
    is_internal = not parsed.scheme and not parsed.netloc and normalized.startswith("/")
    is_external = parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    if not is_internal and not is_external:
        raise ValueError(
            "Enter an internal URL beginning with / or a complete http(s) URL."
        )
    return normalized


class DetailTab(BaseModel):
    """A declarative tab shown on a model's detail view."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    url: str | None = Field(default=None, min_length=1, max_length=2048)
    url_name: str | None = Field(default=None, min_length=1, max_length=255)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Name is required.")
        return normalized

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
        return validate_detail_tab_url(value) if value is not None else None

    @field_validator("url_name")
    @classmethod
    def normalize_url_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("URL name is required.")
        return normalized

    @model_validator(mode="after")
    def validate_url_source(self) -> "DetailTab":
        if (self.url is None) == (self.url_name is None):
            raise ValueError("Provide exactly one of url or url_name.")
        return self


class DetailTabFolder(BaseModel):
    """A top-level folder containing declarative detail tabs."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    tabs: list[DetailTab] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Name is required.")
        return normalized


class DetailTabsConfiguration(BaseModel):
    """A collection of declarative tabs shown on a model's detail view."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="Default", min_length=1, max_length=255)
    tabs: list[DetailTab | DetailTabFolder] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Name is required.")
        return normalized


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

        return {field_name for field_name in self.fields if field_name != "__all__"}


class ApiAccessSettings(BaseModel):
    """Declarative access granted outside a user's assigned policies."""

    anonymous: list[AccessRule] = Field(default_factory=list)
    authenticated: list[AccessRule] = Field(default_factory=list)
    inherit_anonymous_for_authenticated: bool = True


class ApiSettings(BaseModel):
    """
    Configures how Bloomerp API's are set up.

    Settings are:
        - enable_auto_generation: defines whether API endpoints are autogenerated for this model. Defaults to False
        - access: declarative anonymous and authenticated access rules
    """

    enable_auto_generation: bool = False
    serializer_class: str | None = None
    access: ApiAccessSettings = Field(default_factory=ApiAccessSettings)
    nesting: list[ApiNesting] = Field(default_factory=list)

    def get_access_rules(self, *, authenticated: bool) -> list[AccessRule]:
        if not authenticated:
            return list(self.access.anonymous)

        rules = list(self.access.authenticated)
        if self.access.inherit_anonymous_for_authenticated:
            rules.extend(self.access.anonymous)
        return rules

    def has_anonymous_access(self) -> bool:
        return bool(self.access.anonymous)

    def has_authenticated_access(self) -> bool:
        return bool(self.access.authenticated)

    def get_nesting_rules(self, action: str) -> list[ApiNesting]:
        normalized_action = str(action or "").strip().lower()
        return [rule for rule in self.nesting if normalized_action in rule.on_action]


# ------------------------------------
# OBJECT ACTIONS & DATAVIEW ACTIONS
# ------------------------------------
ActionMethod = Literal["GET", "POST"]
ActionModalSize = Literal["sm", "md", "lg", "xl", "full"]
ObjectActionSurface = Literal["detail", "dataview_item"]


@dataclass(frozen=True)
class DataviewActionContext:
    """Describe the accessible collection and selection for a dataview action."""

    request: HttpRequest
    model: type[Model]
    content_type: Any
    preference: Any
    queryset: QuerySet
    querystring: str = ""
    filters: Filters = dataclass_field(default_factory=list)
    selected_ids: list[str] = dataclass_field(default_factory=list)
    operation_context_token: str | None = None


@dataclass(frozen=True)
class ObjectActionContext:
    """Identify the action's record, surface, and optional originating dataview."""

    request: HttpRequest
    model: type[Model]
    content_type: ContentType
    object: Model
    surface: ObjectActionSurface
    dataview: DataviewActionContext | None = None


ActionResponse = HttpResponse | StreamingHttpResponse | None


def _always_show_action(context: ObjectActionContext | DataviewActionContext) -> bool:
    """Show actions that have no configured visibility predicate."""
    return True


class _ActionItem[Context](BaseModel):
    """Define the identity and visibility of an action or group."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(
        min_length=1, description="Stable identifier used to reference the action."
    )
    should_render_func: Callable[[Context], bool] = Field(
        default=_always_show_action,
        description="Python callback that decides whether the action is available in this context.",
    )


class _ActionTrigger[Context](_ActionItem[Context]):
    """Define the label and icon shared by buttons and dropdown triggers."""

    label: str | None = Field(
        default=None, description="Visible label. Omit it for an icon-only trigger."
    )
    icon: str | None = Field(
        default=None, description="CSS classes for the trigger icon."
    )
    shortcut: str | None = Field(
        default=None,
        description="Optional keyboard shortcut for a dataview toolbar trigger.",
    )


class _Action[Context](_ActionTrigger[Context]):
    """Render a button with defaults that can be overridden through its attributes."""

    endpoint: str | Callable[[Context], str] | None = Field(
        default=None,
        description="URL to request or a callback that resolves it from the action context.",
    )
    method: ActionMethod = Field(
        default="POST", description="HTTP method for the action request."
    )
    execution_func: Callable[[Context], ActionResponse] | None = Field(
        default=None,
        description="Server callback invoked through the configured action endpoint.",
    )
    button_attrs: dict[str, Any] | Callable[[Context], dict[str, Any]] = Field(
        default_factory=dict,
        description="HTML attributes or a callback that computes them. Overrides the button defaults.",
    )
    success_message: str | None = Field(
        default=None,
        description="Message displayed when the execution callback returns no response.",
    )

    @model_validator(mode="after")
    def validate_activation(self) -> Self:
        """Require one server request source or explicit client-side attributes."""
        if self.endpoint is not None and self.execution_func is not None:
            raise ValueError("Specify either endpoint or execution_func.")
        if (
            self.endpoint is None
            and self.execution_func is None
            and not self.button_attrs
        ):
            raise ValueError("Specify endpoint, execution_func, or button_attrs.")
        return self

    def default_button_attrs(self) -> dict[str, Any]:
        """Return additional defaults contributed by this button type."""
        return {}

    def get_button_attrs(self, context: Context) -> dict[str, Any]:
        """Combine button-type defaults with attributes configured on the action."""
        overrides = (
            self.button_attrs(context)
            if callable(self.button_attrs)
            else self.button_attrs
        )
        return {**self.default_button_attrs(), **overrides}


class ObjectAction(_Action[ObjectActionContext]):
    """Declare a button that acts on a single record."""


class DataviewAction(_Action[DataviewActionContext]):
    """Declare a button that acts on a dataview or its selection."""


class _ModalButton(BaseModel):
    """Supply standard modal attributes to an ordinary action button."""

    modal_title: str | None = Field(
        default=None, description="Modal heading. Defaults to the button label."
    )
    modal_size: ActionModalSize = Field(default="md", description="Modal width preset.")

    def modal_button_attrs(self, label: str | None) -> dict[str, str]:
        """Build attributes for loading and opening the shared modal."""
        modal_id = "bloomerp-general-use-modal"
        title = self.modal_title or label
        return {
            "hx-target": f"#{modal_id}-body",
            "bloomerp-open-modal": modal_id,
            "bloomerp-set-modal-title-for": modal_id,
            "bloomerp-set-modal-title-to": gettext(title) if title else "",
            "bloomerp-set-modal-size-to": self.modal_size,
        }


class ObjectModalAction(ObjectAction, _ModalButton):
    """Provide modal button defaults for a record action."""

    method: ActionMethod = Field(
        default="GET", description="HTTP method used to load the modal."
    )

    def default_button_attrs(self) -> dict[str, str]:
        """Open the shared modal and load the response into it."""
        return self.modal_button_attrs(self.label)


class DataviewModalAction(DataviewAction, _ModalButton):
    """Provide modal button defaults for a dataview action."""

    method: ActionMethod = Field(
        default="GET", description="HTTP method used to load the modal."
    )

    def default_button_attrs(self) -> dict[str, str]:
        """Open the shared modal and load the response into it."""
        return self.modal_button_attrs(self.label)


class _HTMLAction[Context](_ActionItem[Context]):
    """Render a custom action template with optional context variables."""

    shortcut: str | None = Field(
        default=None, description="Optional dataview toolbar shortcut."
    )
    template_name: str = Field(description="Django template rendered for the action.")
    context_func: Callable[[Context], dict[str, Any]] | None = Field(
        default=None,
        description="Python callback that supplies extra template variables.",
    )


class ObjectHTMLAction(_HTMLAction[ObjectActionContext]):
    """Render an action template for a single record."""


class DataviewHTMLAction(_HTMLAction[DataviewActionContext]):
    """Render an action template in the dataview toolbar."""


class ObjectActionGrouping(_ActionTrigger[ObjectActionContext]):
    """Render record actions and subgroups in a dropdown."""

    actions: "list[ObjectActionDefinition]" = Field(
        description="Child record actions and subgroups in display order."
    )


class DataviewActionGrouping(_ActionTrigger[DataviewActionContext]):
    """Render dataview actions and subgroups in a dropdown."""

    actions: "list[DataviewActionDefinition]" = Field(
        description="Child dataview actions and subgroups in display order."
    )


ObjectActionDefinition = (
    ObjectAction | ObjectModalAction | ObjectHTMLAction | ObjectActionGrouping
)
DataviewActionDefinition = (
    DataviewAction | DataviewModalAction | DataviewHTMLAction | DataviewActionGrouping
)
ObjectActionGrouping.model_rebuild()
DataviewActionGrouping.model_rebuild()


def iter_object_actions(
    actions: Sequence[ObjectActionDefinition],
) -> Iterator[ObjectActionDefinition]:
    """Yield actions and their group members in display order."""
    for action in actions:
        yield action
        if isinstance(action, ObjectActionGrouping):
            yield from iter_object_actions(action.actions)


def get_object_actions(
    model: type[Model],
    *,
    surface: ObjectActionSurface,
    group_all: bool = False,
) -> list[ObjectActionDefinition]:
    """Resolve built-ins and model overrides for an object action surface."""
    from bloomerp.models.object_actions.sidebar import detail_only

    config = get_model_config(model)
    configured = config.object_actions if config else get_default_object_actions
    actions = configured(model) if callable(configured) else configured
    if surface == "detail":
        return actions
    actions = [
        action for action in actions if action.should_render_func is not detail_only
    ]
    if group_all:
        return (
            [ObjectActionGrouping(id="more-actions", actions=actions)]
            if actions
            else []
        )
    grouped_ids = {"create-todo", "contact"}
    grouped = [action for action in actions if action.id in grouped_ids]
    if grouped:
        return [
            ObjectActionGrouping(id="more-actions", actions=grouped),
            *(action for action in actions if action.id not in grouped_ids),
        ]
    return actions


def can_create_dataview_object(context: DataviewActionContext) -> bool:
    """Enable Add only when the model exposes a create route and the user has add permission."""
    from django.urls import NoReverseMatch, reverse

    from bloomerp.permissions.manager import UserPolicyManager
    from bloomerp.utils.models import get_create_view_url

    if not UserPolicyManager(context.request.user).has_global_permission(
        context.model, BloomerpPermission.ADD
    ):
        return False
    try:
        reverse(get_create_view_url(context.model))
    except NoReverseMatch:
        return False
    return True


def get_default_dataview_actions(
    model: type[Model],
    skip: Sequence[str] | None = None,
    include: Sequence[str] | None = None,
) -> list[DataviewActionDefinition]:
    """Return a model's standard toolbar actions, limited by include and then skip.

    An omitted include selects all defaults; an empty include selects none.
    Skip takes precedence when an action appears in both lists.
    """
    template_root = "components/objects/dataview_actions"

    actions: list[DataviewActionDefinition] = [
        DataviewHTMLAction(
            id="filter",
            template_name=f"{template_root}/filter.html",
            shortcut="mod+1",
        ),
        DataviewHTMLAction(
            id="add",
            should_render_func=can_create_dataview_object,
            template_name=f"{template_root}/add.html",
            shortcut="mod+2",
        ),
        DataviewHTMLAction(
            id="bulk-actions",
            template_name=f"{template_root}/bulk_actions.html",
            shortcut="mod+3",
        ),
        DataviewHTMLAction(
            id="export",
            template_name=f"{template_root}/export.html",
            shortcut="mod+4",
        ),
        DataviewHTMLAction(
            id="display-options",
            template_name=f"{template_root}/display_options.html",
            shortcut="mod+5",
        ),
        DataviewHTMLAction(
            id="select-preference",
            template_name=f"{template_root}/select_preference.html",
            shortcut="mod+6",
        ),
    ]
    return [
        action
        for action in actions
        if (include is None or action.id in include)
        and (not skip or action.id not in skip)
    ]


def get_dataview_actions(model: type[Model]) -> list[DataviewActionDefinition]:
    """Resolve the model's configured toolbar list or call its action factory."""
    config = get_model_config(model)
    view_settings = config.model_view_settings if config else None
    configured = (
        view_settings.dataview_actions
        if view_settings
        else get_default_dataview_actions
    )
    return configured(model) if callable(configured) else configured


class DetailViewSettings(BaseModel):
    """Settings regarding detail views for a model.

    An empty ``tab_configurations`` list retains router-derived defaults. Each
    configured layout becomes a named preference, with the first one selected.
    """

    skip_views: Optional[list[str]] = Field(
        default=None,
        description="Optional list of view names to skip when generating the detail view router.",
    )

    layouts: list[FieldLayout] = Field(
        default_factory=list,
        description="Named object-layout configurations for detail and create views.",
    )

    tab_configurations: list[DetailTabsConfiguration] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_layouts(self):
        """Require stable names and exactly one default configured layout."""
        if not self.layouts:
            return self

        names = [layout.name for layout in self.layouts]
        if len(names) != len(set(names)):
            raise ValueError("Detail layout names must be unique.")

        default_count = sum(layout.is_default for layout in self.layouts)
        if default_count != 1:
            raise ValueError(
                "Exactly one configured detail layout must have is_default=True."
            )
        return self

    def get_default_layout(self) -> FieldLayout | None:
        """Return the configured default object layout, if one exists."""
        return next((layout for layout in self.layouts if layout.is_default), None)


class ModelViewSettings(BaseModel):
    """Optional settings for a model's collection views."""

    skip_views: Optional[list[str]] = None

    default_dataviews: list[SerializeAsAny[BaseDataview]] = Field(default_factory=list)

    dataview_actions: (
        list[DataviewActionDefinition]
        | Callable[[type[Model]], list[DataviewActionDefinition]]
    ) = Field(
        default=get_default_dataview_actions,
        description="Toolbar actions or a callable receiving the model. Defaults to the standard toolbar.",
    )

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


class SearchSettings(BaseModel):
    """Optional settings for a model's search functionality."""

    allow_global_search: bool = True

    string_search_fields: list[str] | None = None

    include_search_routes: bool = True


@dataclass(frozen=True, kw_only=True)
class ActivityLogContext:
    """Describe a candidate event and its changed model fields before serialization."""

    action: "ActivityLogAction"
    instance: Model
    actor: AbstractBaseUser | None
    changed_fields: frozenset[str]


@dataclass(frozen=True, kw_only=True)
class ActivityLogDecision:
    """Choose whether to record an event and which field values to snapshot.

    A recorded event includes the changed field names. Each snapshot field also
    includes its full value, even if it did not change. Snapshot fields are
    ignored when ``record`` is false.
    """

    record: bool
    snapshot_fields: frozenset[str] = frozenset()


class ActivityLogSettings(BaseModel):
    """Optional settings for a model's audit functionality."""

    enabled: bool = True
    should_record: Callable[[ActivityLogContext], ActivityLogDecision] | None = Field(
        default=None,
        description="Callback for enabled logging that decides whether to record an event "
        "and which field values to snapshot. Omit it to use standard activity logging.",
    )


class DefaultPolicy(BaseModel):
    """A named policy with optional scoped and explicit global grants."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    access_rule: AccessRule = Field(default_factory=AccessRule)
    global_permissions: list[BloomerpPermission | str] | None = None

    @field_validator("id", "name")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        """Reject blank identifiers and names while storing trimmed text."""
        value = value.strip()
        if not value:
            raise ValueError("Value must not be blank")
        return value


class PermissionSettings(BaseModel):
    """Default database policies declared by a model."""

    default_policies: list[DefaultPolicy] = Field(default_factory=list)

    @field_validator("default_policies")
    @classmethod
    def validate_unique_ids(cls, value: list[DefaultPolicy]) -> list[DefaultPolicy]:
        """Keep policy IDs unique within a model configuration."""
        identifiers = [policy.id for policy in value]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Default policy IDs must be unique within a model")
        return value


class FieldSettings(BaseModel):
    """Declare application-field rendering managed by model metadata sync."""

    field: str
    advanced_rendering: str | None = None


#
StringSearchSettings = SearchSettings


class BloomerpModelConfig(BaseModel):
    """
    Used to define certain bloomerp related meta data on a model.

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
    icon: Optional[str] = Field(
        default="fa fa-cube",
        description="Optional fa icon that represents the model"
    )
    
    description: Optional[str] = Field(
        default=None,
        description="A description of the model",
    )
    
    tiles: list[SerializeAsAny[BaseTileConfig]] = Field(
        default_factory=list,
        description="Optional list of reusable tile configurations associated with this model.",
    )
    field_settings: list[FieldSettings] = Field(default_factory=list)
    is_internal: bool = False
    api_settings: Optional[ApiSettings] = None
    permission_settings: PermissionSettings = Field(default_factory=PermissionSettings)
    create_redirect_url_func: Callable[[Model], str] | None = Field(
        default=None,
        description="Python callback that resolves the redirect URL after object creation.",
    )
    detail_view_settings: Optional[DetailViewSettings] = None
    model_view_settings: Optional[ModelViewSettings] = None
    object_actions: (
        list[ObjectActionDefinition]
        | Callable[[type[Model]], list[ObjectActionDefinition]]
    ) = Field(
        default=get_default_object_actions,
        description="Record actions or a callable receiving the model. Defaults to the standard actions.",
    )

    string_search_settings: SearchSettings = SearchSettings(
        allow_global_search=True, include_search_routes=True
    )

    activity_log_settings: ActivityLogSettings = ActivityLogSettings(enabled=True)

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

    def get_api_access_rules(self, *, authenticated: bool) -> list[AccessRule]:
        if self.api_settings is None:
            return []
        return self.api_settings.get_access_rules(authenticated=authenticated)

    def has_anonymous_api_access(self) -> bool:
        if self.api_settings is None:
            return False
        return self.api_settings.has_anonymous_access()

    def has_authenticated_api_access(self) -> bool:
        if self.api_settings is None:
            return False
        return self.api_settings.has_authenticated_access()

    def get_nesting_rules(self, action: str):
        if self.api_settings is None:
            return []
        return self.api_settings.get_nesting_rules(action)

    def should_enable_api_auto_generation(self) -> bool:
        bloomerp_config: BloomerpConfig = getattr(settings, "BLOOMERP_CONFIG")

        if self.api_settings is None:
            # In this case, use the global setting to determine whether to auto generate API endpoints
            return bloomerp_config.auto_generate_api_endpoints

        return self.api_settings.enable_auto_generation


def get_model_config(
    model_or_object: Type[Model] | Model,
) -> BloomerpModelConfig | None:
    """Returns the bloomerp model config for a model or object (if it exists)

    Args:
        model_or_object (Type[Model] | Model): the model or object

    Returns:
        BloomerpModelConfig | None: the config object
    """
    # Get the model class from either a model class or an instance
    model_class = (
        model_or_object if inspect.isclass(model_or_object) else type(model_or_object)
    )

    # Check if the model has a bloomerp_config attribute
    if hasattr(model_class, "bloomerp_config"):
        config = getattr(model_class, "bloomerp_config")
        if isinstance(config, BloomerpModelConfig):
            return config

    return None
