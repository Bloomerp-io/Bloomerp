# Renderer operations and dataview actions

Bloomerp uses the word "action" for several related but different mechanisms.
Understanding which one owns a request is important when adding an interactive
dataview.

## The three mechanisms

| Mechanism | Entry point | Use it for |
| --- | --- | --- |
| Renderer operation | `BaseDataviewRenderer.handle_action()` | Behavior owned by the rendered preference's dataview renderer and dependent on its configuration or filtered state. |
| Standalone component endpoint | A routed function under `bloomerp.components` | A reusable server capability with its own URL and input contract that does not need dispatch through the selected renderer. |
| Configured dataview action | `DataviewAction`, `DataviewHTMLAction`, or `DataviewModalAction` | Model-configured buttons, HTML, and modals in the dataview toolbar. |

These mechanisms are not interchangeable. In particular,
`BaseDataviewRenderer.handle_action()` is unrelated to the model-configured
`DataviewAction` class despite the shared word "action". It is clearer to call
a `handle_action()` request a **renderer operation**.

## What `handle_action()` does

The shared renderer-operation endpoint has this URL shape:

```text
/components/dataview/<content_type_id>/preference/<preference_id>/renderer-operation/<action>/
```

Its Django URL name is `components_dataview_renderer_operation`. The `action`
path value is an operation identifier chosen by the renderer, such as:

- Kanban: `column`
- Calendar: `unit` and `dates`
- Gantt: `page`, `unscheduled`, and `dates`

The preference ID is the effective preference that rendered the dataview. For
every request, the endpoint:

1. Resolves that preference through `PreferenceManager.get_available()` for the
   current user and content type. An owned live reference to a shared source is
   accepted when the URL contains the source preference ID.
2. Builds the same `DataviewState` used for the main dataview request.
3. Applies row permissions, search, filters, field permissions, renderer-owned
   query parameters, and sorting.
4. Looks up the resolved preference's definition in `DATAVIEW_REGISTRY`.
5. Calls `definition.renderer_cls.handle_action(action, request, state)`.
6. Returns the renderer's `HttpResponse` unchanged.

Resolving an operation does not select, copy, or grant management access to the
preference. This allows a shared or embedded Kanban board to keep using Kanban
operations even when the viewer's globally selected preference is a table.
Generated operation URLs also preserve the rendered request's search and filter
query string, so the rebuilt state represents the same filtered dataview.

The dispatcher does not maintain a global operation catalog. The resolved
preference's renderer interprets the string. Therefore
`/renderer-operation/column/` works only for a preference whose renderer
implements `column`.
The base implementation returns HTTP 400 for unsupported operations.

Use `super().handle_action(action, request, state)` for unknown operation names:

```python
@classmethod
def handle_action(cls, action, request, state):
    if action == "more":
        return cls.render_more(request, state)
    return super().handle_action(action, request, state)
```

This preserves a consistent unsupported-operation response and allows base
behavior to evolve without every renderer reimplementing it.

## When a renderer operation is appropriate

Use `handle_action()` when the operation needs one or more of the following:

- the rendered preference's dataview type;
- the active dataview options in `state.options`;
- the preference's visible or accessible fields;
- the current search and filter query;
- the permission-filtered queryset;
- a renderer-specific partial template.

Typical examples are loading another page inside one lane, returning events for
one calendar unit, or persisting an interaction whose editable fields are
defined by the active dataview configuration.

Use a standalone component endpoint when the operation is an independently
reusable application capability with a stable request contract and does not
need the selected renderer to identify its implementation. Such an endpoint
must perform its own input validation and authorization because it does not
receive `DataviewState` automatically.

## End-to-end Kanban behavior

Kanban currently demonstrates both paths.

### Initial render

1. The main dataview component builds a permission-filtered `DataviewState`.
2. `KanbanDataviewRenderer.get_context_data()` resolves the configured grouping
   field and builds the initial page for every column.
3. `cotton/features/dataviews/kanban.html` renders the board, columns, cards,
   and per-column loader elements.
4. The board declares `bloomerp-component="kanban-board"`.
5. The frontend registry initializes `KanbanBoard`, which adds selection,
   keyboard movement, and drag-and-drop behavior.

### Loading another column page

This is a renderer operation because it depends on the active Kanban options,
the rendered preference, and the currently filtered queryset:

1. `dataview_kanban_cards.html` renders an `hx-get` loader targeting
   `components_dataview_renderer_operation` with `action="column"`.
2. Intersection triggers a request containing `kanban_column` and
   `kanban_page`.
3. The shared endpoint rebuilds the current dataview state and dispatches to
   `KanbanDataviewRenderer.handle_action("column", request, state)`.
4. The renderer resolves the configured grouping field from `state.options`,
   restricts `state.queryset` to that column, paginates it, and renders
   `dataview_kanban_cards.html`.
5. HTMX replaces the loader with the returned cards and, when necessary, a
   loader for the following page.
6. The component lifecycle initializes the newly inserted Kanban cards.

The renderer declares `kanban_column` and `kanban_page` as reserved query
parameters. Without that declaration, the shared state builder would interpret
them as model filters before `handle_action()` received the request.

### Moving a card

Card movement is a renderer operation because its writable field is defined by
the resolved Kanban preference:

1. The rendered board exposes its preference-scoped `move` operation URL in
   `data-kanban-move-url`.
2. `KanbanBoard.ts` optimistically moves the card and posts only `object_id` and
   `group_value` to that URL.
3. `KanbanDataviewRenderer.handle_action("move", request, state)` resolves the
   grouping field from `state.options`; the browser cannot choose another
   field by posting an application-field ID.
4. The renderer requires row-level `change` access to the object and
   field-level `change` access to the configured grouping field. Related lane
   values are also limited to values the viewer may access.
5. It updates the object and returns JSON. The frontend keeps the optimistic
   move on success or restores the original column and shows an error on
   failure.

Sharing a Kanban preference grants access to its board configuration, not write
access to its records. A recipient can move a card only when their independent
model, row, and field policies permit that update. They do not need permission
to manage the owner's shared preference.

For new dataviews, prefer a renderer operation when a mutation is meaningful
only in that renderer and must agree with its active configuration. Prefer a
standalone component endpoint only when the operation is deliberately a
separate reusable capability.

## Implementing a read operation

The following renderer loads another page of a renderer-specific fragment:

```python
from django.http import HttpResponse
from django.shortcuts import render

from bloomerp.dataviews import BaseDataviewRenderer


class TimelineDataviewRenderer(BaseDataviewRenderer):
    reserved_query_params = {"timeline_page"}

    @classmethod
    def handle_action(cls, action, request, state) -> HttpResponse:
        if action != "page":
            return super().handle_action(action, request, state)
        if request.method != "GET":
            return HttpResponse("Method not allowed", status=405)

        page = cls.paginate_object_list(
            state.queryset,
            getattr(state.options, "page_size", 25),
            request.GET.get("timeline_page", 1),
        )
        return render(
            request,
            "my_app/dataviews/timeline_rows.html",
            {
                "content_type_id": state.content_type_id,
                "objects": page.object_list,
                "page_obj": page,
                "fields": state.render_fields,
                "preference": state.preference,
            },
        )
```

The corresponding template can call the shared dispatcher without defining a
new Django route:

```django
{% url 'components_dataview_renderer_operation' content_type_id=content_type_id preference_id=preference.pk action='page' as next_page_url %}

<button
    hx-get="{{ next_page_url }}?timeline_page={{ page_obj.next_page_number }}"
    hx-target="#timeline-rows"
    hx-swap="beforeend"
>
    Load more
</button>
```

## Implementing a mutation operation

`state.queryset` is authorized for **viewing**, not changing. A POST renderer
operation must establish write authorization separately:

1. Reject unsupported HTTP methods.
2. Validate the request body and configured fields.
3. Check global `change` permission where the operation requires it.
4. Check `change` permission for every field being written.
5. Resolve objects through a `UserPolicyManager` change-authorized queryset or
   call `has_access_to_object()` for each object.
6. Use a transaction and row locks for multi-object or concurrent updates when
   appropriate.
7. Return 403 when any requested object or field falls outside the authorized
   set; do not silently update only the permitted subset.

Calendar and Gantt `dates` operations are the reference implementations for
batch mutation behavior. The standalone Kanban move endpoint demonstrates the
equivalent object- and field-permission checks for a single-object update.

## Configured toolbar actions are different

`ModelViewSettings.dataview_actions` controls the actions rendered around a
model's dataview. A configured `DataviewAction` receives a
`DataviewActionContext` and is executed through:

```text
/components/dataview/<content_type_id>/action/<action_id>/
```

Use configured actions for commands such as export, bulk processing, or a
model-specific workflow button that should be available independently of the
selected renderer. Use `handle_action()` for implementation details of the
renderer itself.

Both paths rebuild permission-filtered context, but neither the presence of a
button nor `should_render_func()` replaces authorization inside a mutating
execution function.

## Testing the complete path

Test each layer at the boundary it owns:

- renderer unit tests: operation branching, queryset restriction, pagination,
  and context construction;
- component tests for `components_dataview_renderer_operation`: method, input,
  status, response fragment, and permission behavior;
- end-to-end tests: only behavior that requires the browser, such as an HTMX
  intersection request, drag-and-drop, optimistic movement, DOM rollback, or
  component reinitialization after a swap.

For Kanban, component tests exercise column pagination, shared-preference
resolution, and card movement through the preference-scoped renderer-operation
URL. A browser test is warranted when verifying that dragging calls the right
endpoint and keeps or rolls back the optimistic DOM update.
