# Bloomerp Router

Bloomerp uses a small route registry on top of Django URLs. Views register themselves with `@router.register(...)`; the registry auto-imports view and component modules, expands model/module scoped routes, and finally turns every registered route into Django `path(...)` entries from `bloomerp.urls`.

Use the router for Bloomerp application pages, model pages, object detail tabs/actions, module landing pages, and HTMX/API-like component endpoints that should live inside the Bloomerp URL map.

## How It Loads Routes

The shared router lives in `bloomerp.router`:

```python
from bloomerp.router import router
```

At URL load time, `bloomerp.urls` calls:

```python
urlpatterns.extend(router.create_url_patterns())
```

`create_url_patterns()` auto-imports configured route directories, so decorators in `views/`, `components/`, and direct module files execute before URL patterns are built. Each decorated view becomes a `BloomerpRoute` with:

- `path`: final URL path
- `route_type`: `app`, `module`, `model`, or `detail`
- `name`: human-facing route name
- `url_name`: Django URL name used by `reverse(...)`
- `model`: model class for model/detail routes
- `module`: module config for module/model/detail routes
- `view_type`: class or function view

Class-based views receive route context through `as_view(**kwargs)`. Function views receive route context through Django `path(..., kwargs=...)`. For model routes this usually means `model`; for module routes it means `module`; for detail routes it means both.

## Route Types

The route type decides the URL shape and what context gets attached to the view.

| Type | Scope | Generated URL shape | Use for |
| --- | --- | --- | --- |
| `app` | Global | `/path/` | Global endpoints not tied to a module or model |
| `module` | One or more modules | `/<module>/path/` | Module home pages and module-level tools |
| `model` | A model collection | `/<module>/<model-plural>/path/` | List, create, bulk, profile, and model-wide pages |
| `detail` | One object | `/<module>/<model-plural>/<pk>/path/` | Object overview, edit, delete, files, related tabs/actions |

`<module>` uses `module.route_path` when set, otherwise the module id. `<model-plural>` comes from `model._meta.verbose_name_plural`, lowercased with spaces replaced by hyphens. Detail routes use the `int_or_uuid` converter for `pk`.

## `app` Routes

Use `app` when the route is not naturally owned by a module or model.

```python
@router.register(
    path="components/global_search/",
    name="components_global_search",
)
def global_search(request):
    ...
```

Good fits:

- HTMX components used globally
- authentication helpers
- public API-style endpoints
- utilities such as file signing or SQL metadata endpoints

Avoid `app` for pages that should appear under a module URL or need model/module context. `app` routes reject `models`, `modules`, and `exclude_models`.

## `module` Routes

Use `module` when the page belongs to a Bloomerp module, but not to a single model collection or object.

```python
@router.register(
    path="/",
    name="{module}",
    description="The homepage for the {module} module.",
    route_type="module",
    modules="__all__",
)
class BloomerpModuleHomeView(BaseWorkspaceView, TemplateView):
    ...
```

Good fits:

- module home pages
- dashboards/workspaces scoped to a module
- module-level settings or reports
- SDK/download pages for a specific module

`modules` is required. It can be:

- a module id string
- a `BloomerpModule`/module config object
- a list of modules
- `"__all__"` to create one route per registered module

The view receives `module`.

## `model` Routes

Use `model` when the route operates on a model as a collection or concept, not on one specific object.

```python
@router.register(
    path="/",
    name="{model} List",
    url_name="model",
    description="List of records for {model} model",
    route_type="model",
    exclude_models=[File],
)
class BloomerpListView(BaseBloomerpView, BloomerpModelContextMixin, TemplateView):
    model = None
```

Good fits:

- list views
- create views
- bulk upload/update/export actions
- model-level settings
- pages that choose or filter records
- user profile page, when mounted under a model namespace

`models` can be a model class, list of model classes, or `"__all__"`. `exclude_models` creates routes for every model except the excluded model or list.

For each model, the router asks the module registry for the model's module. If no module is registered for that model, no model route is created. The view receives `model` and `module`.

## `detail` Routes

Use `detail` when the route needs one concrete object id in the URL.

```python
@router.register(
    path="/",
    name="Details",
    url_name="overview",
    description="Overview of object from {model} model",
    route_type="detail",
    models="__all__",
)
class BloomerpDetailOverviewView(BaseBloomerpDetailView):
    ...
```

Good fits:

- object overview pages
- edit/update views
- delete views
- object files
- object activity/comments/document-template tabs
- custom object actions that need `pk`

The generated URL includes `<int_or_uuid:pk>`. Detail views should resolve the object through the model and `pk`, usually via shared detail base classes or `get_object_or_404(self.model, pk=self.kwargs["pk"])`.

The view receives `model` and `module`.

## Picking The Right Type

Ask two questions:

1. Does the URL need an object id?
   Use `detail`.

2. Does the URL belong under a model collection?
   Use `model`.

If neither is true:

- use `module` when the page belongs under a module path
- use `app` when the route is global or utility-like

Examples:

| Need | Type |
| --- | --- |
| `/sales/contacts/` list page | `model` |
| `/sales/contacts/<pk>/` object overview | `detail` |
| `/sales/` module home/dashboard | `module` |
| `/components/global_search/` shared HTMX endpoint | `app` |
| `/sales/contacts/bulk-upload/` | `model` |
| `/sales/contacts/<pk>/files/` | `detail` |

## Names And URL Names

`name` is display-oriented. It supports `{model}` and `{module}` formatting.

```python
name="{model} List"
name="{module}"
description="Overview of object from {model} model"
```

`url_name` is the Django reverse name. If omitted, the router derives it from `name`.

Generated URL names:

- `app`: `<url_name>`
- `module`: `<module_id>_module_<url_name>`
- `model`: `<model_verbose_name_plural>_<url_name>`
- `detail`: `<model_verbose_name_plural>_detail_<url_name>`

Prefer explicit `url_name` for stable public/internal reverse targets. Use descriptive names such as:

```python
url_name="model"
url_name="overview"
url_name="create"
url_name="bulk_upload"
```

## Overriding Routes

Use `override=True` when intentionally replacing an existing route with the same route type, model/module scope, path, or URL name.

```python
@router.register(
    path="/",
    route_type="model",
    models=Contact,
    url_name="model",
    override=True,
)
class CustomContactListView(...):
    ...
```

Without `override=True`, routes are appended unless an existing override route already claims the same slot.

## Skipping Generated Model Or Detail Views

Model configuration can opt out of generated model/detail routes through view settings. During registration, the router checks:

- `config.model_view_settings.skip_views` for `model` routes
- `config.detail_view_settings.skip_views` for `detail` routes

The skip list is compared to the route's `url_name`.

## Access Control

Router registration is not the same as object permission enforcement. Views still need their own permission checks, query filtering, and object access rules.

The router can enforce the global staff-only gate from `BLOOMERP_CONFIG.require_staff_for_access`. A route can override that with `require_staff_for_access` on the view class or via registration kwargs where supported by the registry. View-level permission classes/mixins still decide model and object permissions after the request reaches the view.

For model/detail pages, prefer existing Bloomerp base views and permission services instead of hand-rolling access checks.

## Components

HTMX component endpoints commonly use `app` routes with explicit component paths and names:

```python
@router.register(
    path="components/files/upload/",
    name="components_files_upload",
)
def upload_file(request):
    ...
```

Use these conventions:

- path prefix: `components/...`
- URL name prefix: `components_...`
- return partial HTML or JSON suitable for the component caller
- validate request input explicitly
- enforce permissions in the endpoint

Use `model` or `detail` for component endpoints only when the generated model/detail URL shape is useful and the endpoint should receive `model`/`module` context automatically.

## Late Model Registration

The router stores model/detail route templates. If a model is created after normal route import, call:

```python
router.register_routes_for_model(MyModel)
```

This replays applicable `model` and `detail` route templates for that model, assuming the model is also known to the module registry.

## Practical Checklist

- Use `app` for global utility or component endpoints.
- Use `module` for module home/dashboard/report pages.
- Use `model` for collection-level pages and actions.
- Use `detail` for object-level pages and actions.
- Set explicit `url_name` for anything likely to be reversed.
- Use `{model}` and `{module}` in `name`/`description` for generated routes.
- Use `models="__all__"` only for generic views that truly work for every model.
- Use `exclude_models` for generic routes with known exceptions.
- Keep permission checks in the view or service layer.
- Use `override=True` only when replacing a route intentionally.
