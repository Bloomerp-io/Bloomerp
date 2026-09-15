# Bloomerp Components Guide

Use the relevant section when implementing or reviewing frontend component behavior, a Django component endpoint, fragment markup, HTMX integration, or tests. Current code and tests are authoritative; `.github/instructions/bloomerp_components.instructions.md` contains older lifecycle examples.

## Frontend Architecture

The current implementation lives under `bloomerp/django_bloomerp/bloomerp/static_src/ts/`.

- `components/BaseComponent.ts` owns registration, instance lookup, eager/lazy initialization, and HTMX/browser re-scans.
- `components/data_view_components/BaseDataViewComponent.ts` adds selection, keyboard navigation, context menus, and abort-controller cleanup for data views.
- `main.ts` imports and centrally registers shipped component classes.

Markup declares an instance with a matching ID:

```html
<div bloomerp-component="my-component" data-object-id="{{ object.pk }}"></div>
```

```typescript
// static_src/ts/main.ts
import MyComponent from './components/MyComponent';

registerComponent('my-component', MyComponent);
```

Registration must happen before `setupComponentAutoInit()` runs.

### Initialization and lookup

The registry performs this order:

1. construct the class with its root element;
2. place the instance in the weak registry and compatibility property;
3. set `data-component-initialized="true"`;
4. call `initialize()`.

Do not invoke `initialize()` in a component constructor. Class fields must be initialized before lifecycle setup executes.

`getComponent(element)` returns an existing instance or lazily constructs and initializes one when the element declares a registered component ID.

Automatic scanning currently occurs on:

- initial DOM readiness;
- `htmx:afterSwap`;
- `htmx:oobAfterSwap`;
- `htmx:load`;
- `htmx:historyRestore`;
- browser `pageshow` for back-forward cache restoration.

After normal, OOB, and load events, the registry invokes `onAfterSwap()` on initialized components in the affected scope; normal swaps also include initialized ancestors. OOB swaps refresh callbacks across the document. Override `onAfterSwap()` only when an existing component must reconcile replaced descendants, cached references, or edit state.

The instance registry prevents duplicate initialization of the same connected element. A stale `data-component-initialized` attribute is not treated as proof that a live instance exists.

### Cleanup

For a group of listeners, prefer this pattern:

```typescript
export default class MyComponent extends BaseComponent {
    private lifecycle: AbortController | null = null;

    public initialize(): void {
        if (!this.element) return;
        this.lifecycle?.abort();
        this.lifecycle = new AbortController();
        this.element.addEventListener('click', this.onClick, {
            signal: this.lifecycle.signal,
        });
    }

    private onClick = (event: MouseEvent): void => {
        // ...
    };

    public override destroy(): void {
        this.lifecycle?.abort();
        this.lifecycle = null;
        super.destroy();
    }
}
```

Stored handler references with `removeEventListener` remain appropriate. Also clean up fetch controllers, observers, timers, third-party editors, sortable instances, and child objects owned by the component.

Do not assume every DOM removal automatically calls `destroy()`. Components with expensive resources that can be removed by HTMX should follow nearby established `htmx:beforeCleanupElement` handling where needed.

## Templates and Cotton

Use an ordinary fragment under `templates/components/...` when it is specifically the response body of a backend component endpoint.

Use a Django Cotton component under `templates/cotton/...` when the markup is a reusable composable UI primitive. Invoke nested paths with Cotton syntax such as `<c-sidebar.body>`. Follow a nearby Cotton component's slots, attributes, and naming rather than inventing a parallel interface.

Keep runtime values in `data-*` attributes and parse them defensively. Ensure HTML IDs and CSS/HTMX selectors remain unique when a component may appear multiple times.

## Backend Component Endpoints

Import the shared router with:

```python
from bloomerp.router import router
```

For a global component endpoint, use the default `app` route and a stable URL name:

```python
@router.register(
    path="components/widgets/preview/",
    url_name="components_widgets_preview",
)
def preview_widget(request: HttpRequest) -> HttpResponse:
    ...
```

`name` is human-facing route metadata. Existing endpoints sometimes use it as the URL-name fallback, but new code that is reversed should specify `url_name` explicitly.

Most HTMX components are global `app` routes. Use `model` or `detail` only when the generated module/model/object URL shape and injected route context are intentional. Consult `docs/developers/bloomerp_router.md` for route types, generated names, overrides, and late model registration.

Endpoint responsibilities commonly include:

- enforcing login, global capability, row/object access, and field access as required;
- resolving content types and objects with scoped `get_object_or_404` lookups;
- validating method, query, form, file, and JSON input;
- filtering querysets before rendering or serializing them;
- returning a fragment or JSON contract expected by the caller;
- keeping non-trivial business logic in a service or focused helper.

Use appropriate HTTP status codes. For HTMX navigation and refresh behavior, prefer helpers from `django_htmx.http` such as `HttpResponseClientRedirect` or `HttpResponseClientRefresh` when they express the contract clearly.

Serialize structured event details as JSON:

```python
response["HX-Trigger"] = json.dumps(
    {"bloomerp:object-created": {"object_id": str(obj.pk)}}
)
```

Also consider `HX-Trigger-After-Swap`, `HX-Redirect`, or `HX-Refresh` when that timing or behavior is required. Namespace new cross-component events when collision is plausible, and keep the TypeScript listener payload in sync.

## HTMX Patterns

- Initial fragment load: `hx-get` plus `hx-trigger="load"`.
- Debounced input: `keyup changed delay:<duration>` with an explicit target and swap mode.
- Forms: GET renders the form; invalid POST returns the form fragment with errors; successful POST emits the smallest redirect, refresh, replacement, or event contract needed.
- `outerHTML`: remember that the original target may be detached by `afterSwap`; the global lifecycle already falls back to scanning the document in that case.
- OOB swaps: use them deliberately and ensure affected parent components can refresh through `onAfterSwap()`.

## Testing

For routed endpoints, prefer `BloomerpComponentTestCase` with `RequestScenario` and `ExpectedResult` from `bloomerp.tests.base`. It exercises request parsing, authentication, permissions, status, headers, HTML, and JSON using the project fixtures.

```python
class TestPreviewWidgetComponent(BloomerpComponentTestCase):
    view_name = "components_widgets_preview"

    def get_test_scenarios(self) -> list[RequestScenario]:
        return [
            RequestScenario(
                name="Renders the preview",
                query_params={"value": "example"},
                expected=ExpectedResult(
                    status_code=200,
                    response_validators=[self.contains_text("example")],
                ),
            )
        ]
```

Use:

- a focused unit test for pure rendering or transformation logic;
- a widget test when server-rendered form markup must point to the component correctly;
- a component test for the routed server contract;
- an end-to-end test only when browser JavaScript, event dispatch, focus, navigation, or an HTMX request/swap must be verified.

See `docs/developers/testing/component-test-case.md` and `request-test-case.md` for the current scenario API.
