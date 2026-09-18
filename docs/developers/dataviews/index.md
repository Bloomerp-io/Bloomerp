# Dataviews

Dataviews are pluggable collection renderers for Bloomerp models. A dataview
definition combines:

- a Pydantic configuration model;
- a renderer that receives Bloomerp's permission-filtered state;
- user-facing metadata used by the view selector;
- optional model-availability and display-field behavior.

Applications can add dataviews without changing Bloomerp itself. Put the
registration in a top-level `dataviews.py` module or `dataviews` package inside
an installed Django application. Bloomerp discovers those modules during
application startup.

## Public API

Import extension primitives from `bloomerp.dataviews`:

```python
from bloomerp.dataviews import (
    BaseDataview,
    BaseDataviewRenderer,
    DataviewPagination,
    DataviewState,
    DataviewTypeDefinition,
    register_dataview,
)
```

The package also exports `DATAVIEW_REGISTRY`, `DataviewRegistry`, `PageSize`,
`application_field_choices`, `application_field_name_choices`,
`page_size_choices`, and `get_dataview_type_choices`. These names form the
supported dataview extension surface. Code outside Bloomerp should not import
component helpers or individual registry internals.

## Minimal dataview

Create `my_app/dataviews.py`:

```python
from typing import Literal

from bloomerp.dataviews import (
    BaseDataview,
    BaseDataviewRenderer,
    DataviewPagination,
    DataviewTypeDefinition,
    register_dataview,
)


class TimelineDataview(BaseDataview):
    view_type: Literal["timeline"] = "timeline"
    date_field: str | None = None
    page_size: int = 25

    application_field_options = {"date_field": "single"}


class TimelineDataviewRenderer(BaseDataviewRenderer):
    template_name = "my_app/dataviews/timeline.html"
    reserved_query_params = {"timeline_page"}

    @classmethod
    def paginate_queryset(
        cls,
        queryset,
        preference,
        request,
        options=None,
    ) -> DataviewPagination:
        page = cls.paginate_object_list(
            queryset,
            getattr(options, "page_size", 25),
            request.GET.get("timeline_page", 1),
        )
        return DataviewPagination(queryset=page, page_obj=page)

    def get_context_data(self, pagination):
        context = super().get_context_data(pagination)
        context["timeline_date_field"] = getattr(
            self.options,
            "date_field",
            None,
        )
        return context


register_dataview(
    DataviewTypeDefinition(
        key="timeline",
        label="Timeline",
        description="Displays records on a timeline.",
        icon="fa fa-stream",
        renderer_cls=TimelineDataviewRenderer,
        config_cls=TimelineDataview,
    )
)
```

Then add `my_app/templates/my_app/dataviews/timeline.html`. The base renderer
supplies `content_type_id`, `queryset`, `fields`, `avatar_field`, `preference`,
and `object_actions`. Use `get_context_data()` to add view-specific values.

Registration fails during startup when:

- the registry key and definition key differ;
- the renderer does not extend `BaseDataviewRenderer`;
- the config does not extend `BaseDataview`;
- the config's `view_type` default differs from the definition key;
- `application_field_options` names an option that the config does not define;
- an application-field option uses a cardinality other than `single` or
  `multiple`;
- the key is already registered.

This early validation is intentional: an invalid extension should fail at
startup rather than when a user opens a collection view.

## Configuration and option forms

Fields added by a `BaseDataview` subclass are persisted in
`UserListViewPreference.options`. Common fields such as `name`, `is_default`,
`display_fields`, `default_filters`, and `split_view_enabled` are model-default
settings and are not persisted as view-specific options.

Bloomerp creates a Django options form from the Pydantic fields. Override
`create_form_field(name, field_info, state)` when an option needs model-aware
choices, or override `form_factory(state)` when the complete form is custom.
Only use `state.accessible_fields` for field choices so the form does not
expose fields the current user cannot view.

Options that contain developer-facing `ApplicationField` names must be listed
in `application_field_options`:

```python
application_field_options = {
    "primary_field": "single",
    "group_fields": "multiple",
}
```

During configured-default creation, Bloomerp validates those names and omits
fields that are inaccessible to the user. Other options are serialized
unchanged. Override `resolve_options(resolve_field_name)` only when a dataview
needs a different persisted representation.

## Renderer lifecycle

The runtime calls renderer hooks in this order:

1. Bloomerp resolves the selected preference and validates its configuration.
2. It builds a row-permission-filtered queryset and accessible render fields.
3. `get_reserved_query_params()` identifies parameters that must not become
   model filters.
4. `apply_sorting(queryset, request, fields, options)` may return an updated
   queryset and shell context.
5. `paginate_queryset(queryset, preference, request, options)` returns a
   `DataviewPagination`.
6. Bloomerp constructs the renderer with a `DataviewState` and calls
   `render(pagination)`.
7. `render()` calls `get_context_data(pagination)` and renders `template_name`.

The default sorting and pagination hooks leave the queryset unchanged. Override
only the hooks the dataview needs. Query parameters owned by the dataview must
be listed in `reserved_query_params`; otherwise Bloomerp will try to interpret
them as model filters.

`DataviewState.queryset` has already passed row-level filtering, and
`DataviewState.fields` reflects field visibility. Renderers must preserve those
boundaries. Do not replace the queryset with an unrestricted model manager or
look up configured fields outside `state.fields` without performing the same
permission checks.

## Renderer operations

Interactive dataviews may override:

```python
@classmethod
def handle_action(cls, action, request, state):
    ...
```

Requests are dispatched through the active dataview's renderer-operation
endpoint. Return the superclass response for unknown actions. Mutation actions
must validate the HTTP method and check change permission for every affected
object; receiving a permission-filtered view queryset does not itself grant
write access.

## Availability and display fields

`DataviewTypeDefinition` accepts two optional controls:

```python
DataviewTypeDefinition(
    ...,
    requires_display_fields=False,
    available_for_model=lambda model: hasattr(model, "starts_at"),
)
```

`requires_display_fields` controls whether the field-visibility editor is
shown. `available_for_model` controls whether users may select the dataview for
a model. Keep the availability callable deterministic and free of request- or
database-specific state.

## Model defaults

Registered config subclasses can be used directly in a model's
`ModelViewSettings.default_dataviews`:

```python
ModelViewSettings(
    default_dataviews=[
        TimelineDataview(
            name="Schedule",
            date_field="starts_at",
            display_fields=["title", "starts_at"],
        )
    ]
)
```

Exactly one configured dataview must have `is_default=True`. Display fields,
field-backed options, and default filters are resolved against the target
model and the creating user's field permissions when preferences are first
materialized.

## Testing

Extend `BloomerpDataviewTestCase` to verify the universal registration contract,
then add focused tests for configuration or renderer behavior. Use component
tests for renderer-operation endpoints and end-to-end tests only for browser
interaction. See [Dataview test cases](../testing/dataview-test-case.md).
