from typing import Literal, Optional
from bloomerp.config.definition import BloomerpConfig
from bloomerp.models.base_bloomerp_model import FieldLayout
from bloomerp.field_types import Lookup
from pydantic import BaseModel, Field
from django.conf import settings

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


class BloomerpModelConfig(BaseModel):
    """
    Used to define certain bloomerp related meta data on a model. 

    Settings are:
        - modules: a list of modules to which this model belongs.
        - layout: a layout object defining how the default CRUD layout for users is.

    Usage
    ```python
    from bloomerp.models.definition import BloomerpModelConfig

    class Lorum(BloomerpModel):
        bloomerp_config = BloomerpModelConfig(
            ...
        )
    ``` 
    """

    modules: Optional[list[str]] = None

    layout: Optional[FieldLayout] = None

    allow_string_search: bool = True

    is_internal: bool = False

    api_settings: Optional[ApiSettings] = None

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

    def should_enable_api_auto_generation(self) -> bool:
        bloomerp_config : BloomerpConfig = getattr(settings, "BLOOMERP_CONFIG")

        if self.api_settings is None:
            # In this case, use the global setting to determine whether to auto generate API endpoints
            return bloomerp_config.auto_generate_api_endpoints
        
        return self.api_settings.enable_auto_generation
