# Bloomerp components guide (frontend + backend)

This reference condenses `.github/instructions/bloomerp_components.instructions.md` so the skill can be applied without re-reading the source each turn.

## Frontend components

### Base model
- `BaseComponent` provides `element`, `initialize()`, `destroy()`.
- `BaseDataViewComponent` is the foundation for rich data UIs (table/kanban/calendar style components).

### Registration and markup
- Register once: `registerComponent('component-id', ComponentClass)`.
- Instantiate from markup: `<div bloomerp-component="component-id">...</div>`.

### Initialization lifecycle
- Auto init on:
  - `DOMContentLoaded`
  - `htmx:afterSwap`
  - `htmx:historyRestore`
  - `pageshow` (bfcache restore)
- Use lazy access via `getComponent(element)` when needed.

### Cotton integration
- If the component can be seen as a composable UI element, than create a cotton component. This means that the html should live in templates/cotton/... and can be accessed using <c-path1.path2. ...> within the templates.
- For an example of the cotton integration, look at sidebar/body.html

### Frontend best practices
- Always guard for null element.
- Keep handler references as instance properties for `removeEventListener` in `destroy()`.
- Keep state local to each instance.
- Use `data-*` attributes for runtime config.
- Prefer event-driven communication (`CustomEvent`) for decoupled parent-child interactions.

## Backend components

### Router convention
- Register component endpoints with `registries.route_registry.router`:

```python
@router.register(path="components/my-component/", name="components_my_component")
def my_component(request: HttpRequest) -> HttpResponse:
    ...
```

### Responsibilities
- Process HTMX requests.
- Execute business logic and permission checks.
- Query/filter data.
- Render partial templates used for dynamic swaps.

### Backend best practices
- Use `get_object_or_404` for object/content-type retrieval.
- Apply per-user query filtering.
- Validate all input and return meaningful errors.
- Use consistent naming:
  - Route path: `components/<resource>/<action>/`
  - Template: `components/<resource>/<action>.html`
- Return appropriate HTTP status codes.
- Extract non-trivial branching/transformation into helper functions.

## HTMX patterns to support
- Initial loading with `hx-get` + `hx-trigger="load"`.
- Debounced live search via `keyup changed delay:*`.
- Form fetch/submit flows where invalid submissions return form fragments.
- Trigger post-action events with:

```python
response['HX-Trigger'] = 'dataUpdated,formClosed'
```

## Migration note
If legacy `urls.py` entries define component routes, migrate to route decorators in component modules for discoverability and consistent registration.

