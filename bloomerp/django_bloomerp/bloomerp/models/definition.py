import inspect
import json
import re
from collections.abc import Callable
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
from pydantic.json_schema import SkipJsonSchema

from bloomerp.config.definition import BloomerpConfig
from bloomerp.dataviews.definition import BaseDataview
from bloomerp.field_types.registry import FormFactory, WidgetFactory
from bloomerp.filters.definition import Filters
from bloomerp.models.actions.dataview.add import (
    can_create_dataview_object,  # noqa: F401
)
from bloomerp.models.actions.dataview.builtins import (  # noqa: F401
    get_dataview_actions,
    get_default_dataview_actions,
)
from bloomerp.models.actions.object.builtins import get_default_object_actions
from bloomerp.models.actions.object.resolution import (  # noqa: F401
    get_object_actions,
    iter_object_actions,
)
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
ActionDrawerSize = Literal["sm", "md", "lg", "xl", "2xl", "4xl", "6xl", "full"]
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
    component_args: dict[str, str] = dataclass_field(default_factory=dict)
    render_id: str | None = None
    create_url: str | None = None


@dataclass(frozen=True)
class ObjectActionContext:
    """Identify the action's record, surface, and optional originating dataview."""

    request: HttpRequest
    model: type[Model]
    content_type: ContentType
    object: Model
    surface: ObjectActionSurface
    dataview: DataviewActionContext | None = None

    @property
    def button_size(self) -> Literal["xs", "sm"]:
        """Return the standard button size for this record's action surface."""
        return "sm" if self.surface == "detail" else "xs"


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
        description="HTML attributes or a callback. An href renders a link, and an empty href hides it.",
    )
    success_message: str | None = Field(
        default=None,
        description="Message displayed when the execution callback returns no response.",
    )
    refresh_on_success: Literal["dataview"] | None = Field(
        default=None,
        description="Refresh the originating Dataview when the execution callback returns None.",
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

    refresh_on_success: Literal["item", "dataview"] | None = Field(
        default=None,
        description=(
            "Refresh the item in place, or the Dataview if the action changes selection, "
            "grouping, or order. Applies when the execution callback returns None."
        ),
    )


class _DataviewSelectionAction(BaseModel):
    """Allow Dataview actions to appear in the selection controls."""

    requires_selection: bool = Field(
        default=False,
        description="Show this action when the Dataview has a record selection.",
    )


class DataviewAction(_Action[DataviewActionContext], _DataviewSelectionAction):
    """Declare a button that acts on a dataview or its selection."""

    forward_dataview_context: bool = Field(
        default=True,
        description="Send the originating Dataview's filters and selection to the action.",
    )


class _ModalButton(BaseModel):
    """Supply standard modal attributes to an ordinary action button."""

    modal_id: str = Field(
        default="bloomerp-general-use-modal",
        min_length=1,
        description="ID of the modal to open and load.",
    )
    title: str | None = Field(
        default=None, description="Modal heading. Defaults to the button label."
    )
    size: ActionModalSize = Field(default="md", description="Modal width preset.")
    body_class: str | None = Field(
        default=None, description="CSS classes to apply to the modal body for this opening."
    )

    def modal_button_attrs(self, label: str | None) -> dict[str, str]:
        """Build attributes for loading and opening the configured modal."""
        modal_id = self.modal_id
        title = self.title or label
        attrs = {
            "hx-target": f"#{modal_id}-body",
            "bloomerp-open-modal": modal_id,
            "bloomerp-set-modal-title-for": modal_id,
            "bloomerp-set-modal-title-to": gettext(title) if title else "",
            "bloomerp-set-modal-size-to": self.size,
        }
        if self.body_class:
            attrs["bloomerp-set-modal-body-class-to"] = self.body_class
        return attrs


class _DrawerButton(BaseModel):
    """Supply standard drawer attributes to an ordinary action button."""

    drawer_id: str = Field(
        default="bloomerp-general-use-drawer",
        min_length=1,
        description="ID of the drawer to open and load.",
    )
    title: str | None = Field(
        default=None, description="Drawer heading. Defaults to the button label."
    )
    size: ActionDrawerSize = Field(default="md", description="Drawer width preset.")
    body_class: str | None = Field(
        default=None, description="CSS classes to apply to the drawer body for this opening."
    )

    def drawer_button_attrs(self, label: str | None) -> dict[str, str]:
        """Build attributes for loading and opening the configured drawer."""
        drawer_id = self.drawer_id
        title = self.title or label
        attrs = {
            "hx-target": f"#{drawer_id}-body",
            "hx-push-url": "false",
            "bloomerp-open-drawer": drawer_id,
            "bloomerp-set-drawer-title-for": drawer_id,
            "bloomerp-set-drawer-title-to": gettext(title) if title else "",
            "bloomerp-set-drawer-size-to": self.size,
        }
        if self.body_class:
            attrs["bloomerp-set-drawer-body-class-to"] = self.body_class
        return attrs


class ObjectModalAction(ObjectAction, _ModalButton):
    """Provide modal button defaults for a record action."""

    method: ActionMethod = Field(
        default="GET", description="HTTP method used to load the modal."
    )

    def default_button_attrs(self) -> dict[str, str]:
        """Open the configured modal and load the response into it."""
        return self.modal_button_attrs(self.label)


class ObjectDrawerAction(ObjectAction, _DrawerButton):
    """Provide drawer button defaults for a record action."""

    method: ActionMethod = Field(
        default="GET", description="HTTP method used to load the drawer."
    )

    def default_button_attrs(self) -> dict[str, str]:
        """Open the configured drawer and load the response into it."""
        return self.drawer_button_attrs(self.label)


ObjectActionTarget = Literal["main", "modal", "drawer"]


class DataviewDrawerAction(DataviewAction, _DrawerButton):
    """Provide drawer button defaults for a dataview action."""

    size: ActionDrawerSize = Field(default="2xl", description="Drawer width preset.")
    method: ActionMethod = Field(
        default="GET", description="HTTP method used to load the drawer."
    )

    def default_button_attrs(self) -> dict[str, str]:
        """Open the configured drawer and load the response into it."""
        return self.drawer_button_attrs(self.label)


class DataviewModalAction(DataviewAction, _ModalButton):
    """Provide modal button defaults for a dataview action."""

    method: ActionMethod = Field(
        default="GET", description="HTTP method used to load the modal."
    )

    def default_button_attrs(self) -> dict[str, str]:
        """Open the configured modal and load the response into it."""
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


class DataviewHTMLAction(_HTMLAction[DataviewActionContext], _DataviewSelectionAction):
    """Render an action template in the dataview toolbar."""


class _ActionGrouping[Context](_ActionTrigger[Context]):
    """Configure the shared dropdown trigger for a group of actions."""

    button_size: Literal["xs", "sm", "md", "lg"] | None = Field(
        default="sm", description="Size of the dropdown trigger button."
    )


class ObjectActionGrouping(_ActionGrouping[ObjectActionContext]):
    """Render record actions and subgroups in a dropdown."""

    button_size: Literal["xs", "sm", "md", "lg"] | None = Field(
        default=None, description="Dropdown trigger size. Defaults to the record surface size."
    )
    actions: "list[ObjectActionDefinition]" = Field(
        description="Child record actions and subgroups in display order."
    )


class DataviewActionGrouping(_ActionGrouping[DataviewActionContext], _DataviewSelectionAction):
    """Render dataview actions and subgroups in a dropdown."""

    actions: "list[DataviewActionDefinition]" = Field(
        description="Child dataview actions and subgroups in display order."
    )


ObjectActionDefinition = (
    ObjectAction | ObjectModalAction | ObjectDrawerAction | ObjectHTMLAction | ObjectActionGrouping
)
DataviewActionDefinition = (
    DataviewAction | DataviewModalAction | DataviewDrawerAction | DataviewHTMLAction | DataviewActionGrouping
)
ObjectActionGrouping.model_rebuild()
DataviewActionGrouping.model_rebuild()


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

    embedded_queryset_scope: Callable[[HttpRequest, QuerySet, dict[str, str]], QuerySet] | None = Field(
        default=None,
        description="Narrow the authorized queryset for a signed inline Dataview layout.",
    )

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
    should_record: SkipJsonSchema[
        Callable[[ActivityLogContext], ActivityLogDecision] | None
    ] = Field(
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
    widget_factory: Optional[WidgetFactory] = None
    form_factory: Optional[FormFactory] = None


#
StringSearchSettings = SearchSettings


class BloomerpModelConfig(BaseModel):
    """
    Used to define certain bloomerp related meta data on a model.
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
