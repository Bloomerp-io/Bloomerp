---
applyTo: '**/components'
---

# Bloomerp Frontend Components Instructions

## Overview & Goals

Bloomerp Components is a TypeScript-based component system designed to encapsulate interactive UI behavior and state management. Components bridge the gap between HTML templates and JavaScript logic, providing:

- **Modular encapsulation**: Each component owns its own initialization, state, and cleanup
- **Reusability**: Components can be registered once and instantiated multiple times across the UI
- **HTMX integration**: Seamless component initialization and re-initialization after HTMX dynamic content swaps
- **Lifecycle management**: Proper initialization and destruction to prevent memory leaks and stale event listeners
- **Lazy initialization**: Components can be instantiated on-demand or eagerly during page load

## Component Architecture

### Base Class Hierarchy

```
BaseComponent (abstract)
├── BaseDataViewComponent (data display components)
│   ├── DataTable
│   ├── Kanban
│   └── Calendar
└── [Other specialized components]
```

### BaseComponent

The foundational class that all components inherit from:

```typescript
class BaseComponent {
    public element: HTMLElement | null = null;

    constructor(element?: HTMLElement) {
        if (element) {
            this.element = element;
            this.initialize();
        }
    }

    public initialize(): void {
        // Override in subclasses
    }

    public destroy(): void {
        // Override if cleanup needed (remove listeners, etc.)
    }
}
```

**Key points:**
- `element`: The root HTML element the component is attached to
- `initialize()`: Called automatically after construction; override to set up your component
- `destroy()`: Called when removing a component; override to clean up event listeners and resources

## How Components Work

### 1. Registration

Components must be registered before they can be instantiated:

```typescript
import { registerComponent } from '../BaseComponent';
import { DataTable } from './DataTable';

registerComponent('datatable', DataTable);
```

This maps a string ID (`'datatable'`) to the component class.

### 2. HTML Markup

Components are declared in HTML using the `bloomerp-component` attribute:

```html
<div bloomerp-component="datatable" data-column-index="0" data-row-index="0">
    <!-- Component content -->
</div>
```

The attribute value must match a registered component ID.

### 3. Initialization Process

Components are initialized automatically through several mechanisms:

**On Page Load:**
- When the DOM is ready, `initComponents()` scans for elements with `bloomerp-component` attributes
- For each element found, the corresponding registered component class is instantiated
- The component's `initialize()` method is called immediately

**After HTMX Swaps:**
- HTMX's `htmx:afterSwap` event listener triggers component re-initialization
- Only the swapped container is scanned for new components
- Existing instances are preserved (checked via instance registry)

**Browser History Restoration:**
- `htmx:historyRestore` event rescans the entire document
- `pageshow` event handles back-forward cache (bfcache) restoration

**Lazy Initialization:**
- Components can be instantiated on-demand via `getComponent(element)`
- Useful for dynamically accessing component instances

### 4. Lifecycle

```
Element with bloomerp-component attribute exists
    ↓
initComponents() discovers element
    ↓
Registered component class instantiated with element
    ↓
Component.initialize() called (override to add logic)
    ↓
Component active and listening to events
    ↓
When element removed or component explicitly destroyed
    ↓
Component.destroy() called (override to clean up)
    ↓
Component instance removed from registry
```

## Creating New Components

### Basic Component Example

```typescript
import BaseComponent, { registerComponent } from '../BaseComponent';

export class MyComponent extends BaseComponent {
    private clickHandler: ((e: MouseEvent) => void) | null = null;

    public initialize(): void {
        if (!this.element) return;

        // Set up event listeners
        this.clickHandler = (e: MouseEvent) => this.handleClick(e);
        this.element.addEventListener('click', this.clickHandler);

        // Initialize state
        console.log('MyComponent initialized');
    }

    private handleClick(e: MouseEvent): void {
        console.log('Clicked!', e.target);
    }

    public destroy(): void {
        // Clean up event listeners
        if (this.clickHandler && this.element) {
            this.element.removeEventListener('click', this.clickHandler);
        }
        this.clickHandler = null;
    }
}

// Register the component
registerComponent('my-component', MyComponent);
```

### Data View Component Example (Advanced)

For components that manage complex data and interactions (like DataTable):

```typescript
import { BaseDataViewComponent } from './BaseDataViewComponent';
import { BaseDataViewCell } from './BaseDataViewCell';

export class MyDataView extends BaseDataViewComponent {
    protected cellClass = MyDataViewCell;
    public currentCell: MyDataViewCell | null = null;

    public initialize(): void {
        super.initialize();
        // Additional initialization
    }

    public handleNavigation(key: string, hasModifier: boolean): void {
        // Handle keyboard navigation
    }

    public constructContextMenu(): ContextMenuItem[] {
        // Build context menu for right-click interactions
        return [];
    }
}
```

## Best Practices

### 1. Always Clean Up Resources

Override `destroy()` to remove event listeners and clean up:

```typescript
public destroy(): void {
    if (this.eventListener && this.element) {
        this.element.removeEventListener('click', this.eventListener);
    }
    this.eventListener = null;
}
```

### 2. Check Element Existence

Always verify `this.element` exists before using it:

```typescript
public initialize(): void {
    if (!this.element) return;
    // Safe to use this.element
}
```

### 3. Store Event Handler References

Store event handler functions as instance properties to enable proper cleanup:

```typescript
private clickHandler: ((e: MouseEvent) => void) | null = null;

public initialize(): void {
    if (!this.element) return;
    this.clickHandler = (e) => this.handleClick(e);
    this.element.addEventListener('click', this.clickHandler);
}

public destroy(): void {
    if (this.clickHandler && this.element) {
        this.element.removeEventListener('click', this.clickHandler);
    }
}
```

### 4. Use Data Attributes for Configuration

Pass configuration via HTML data attributes:

```html
<div bloomerp-component="datatable" 
     data-column-index="0" 
     data-filterable="true"
     data-application-field-name="name">
</div>
```

```typescript
public initialize(): void {
    if (!this.element) return;
    
    const colAttr = this.element.getAttribute('data-column-index');
    this.columnIndex = colAttr ? Number.parseInt(colAttr, 10) : -1;
    
    this.filterable = this.element.getAttribute('data-filterable') === 'true';
}
```

### 5. Leverage the Instance Registry

Use `getComponent()` to access component instances programmatically:

```typescript
import { getComponent } from '../BaseComponent';

const cellElement = document.querySelector('[bloomerp-component="datatable-cell"]');
const cellComponent = getComponent(cellElement) as DataTableCell;
if (cellComponent) {
    cellComponent.doSomething();
}
```

### 6. Avoid Global State

Keep component state within the component instance:

```typescript
// Good: State is per-instance
export class MyComponent extends BaseComponent {
    private isActive: boolean = false;
}

// Bad: Global state (shared across all instances)
let isActive = false;
export class MyComponent extends BaseComponent {
    // ...
}
```

### 7. Handle HTMX Integration Gracefully

Components will be re-initialized after HTMX swaps. Be aware that:

- The instance registry prevents double-initialization
- `data-component-initialized` attribute marks initialized elements
- After history restoration, components are re-scanned and re-initialized
- Previous event listeners will be preserved by the old component instance until the element is actually removed

## Component Auto-Initialization

The system automatically initializes components on:

1. **DOMContentLoaded**: Initial page load
2. **htmx:afterSwap**: After HTMX swaps new content
3. **htmx:historyRestore**: When HTMX history is restored
4. **pageshow**: Browser back-forward cache restoration

You typically don't need to manually call `initComponents()` unless you're dynamically inserting HTML outside of HTMX.

## Accessing Components from Other Code

```typescript
import { getComponent } from '../BaseComponent';

// Get instance from element
const element = document.querySelector('[bloomerp-component="datatable"]');
const datatable = getComponent(element) as DataTable;

if (datatable) {
    datatable.moveCellDown();
}
```

## Common Patterns

### Pattern: Parent-Child Components

Parent components can access child components:

```typescript
export class DataTable extends BaseDataViewComponent {
    public initialize(): void {
        super.initialize();
        
        // Access child cells
        const cells = this.element?.querySelectorAll('[bloomerp-component="datatable-cell"]');
        cells?.forEach(cellEl => {
            const cell = getComponent(cellEl as HTMLElement) as DataTableCell;
            if (cell) {
                // Do something with child component
            }
        });
    }
}
```

### Pattern: Event-Driven Communication

Use custom events for component communication:

```typescript
export class MyComponent extends BaseComponent {
    public initialize(): void {
        if (!this.element) return;
        this.element.addEventListener('click', () => {
            this.element?.dispatchEvent(new CustomEvent('my-action', {
                detail: { data: 'some data' }
            }));
        });
    }
}

// Listen from parent
parent.element?.addEventListener('my-action', (e: Event) => {
    const customEvent = e as CustomEvent;
    console.log('Event data:', customEvent.detail);
});
```

---

# Bloomerp Backend Components Instructions

## Overview & Goals

Backend components are Django view functions located in the `components/` folder that handle HTMX requests and return rendered HTML. They form the server-side counterpart to frontend components, responsible for:

- **Server-side state management**: Querying databases, filtering data, and managing application state
- **Business logic execution**: Validating user input, processing data, and applying permissions
- **HTML rendering**: Returning templated HTML that can be swapped into the page via HTMX
- **CRUD operations**: Creating, reading, updating, and deleting application objects
- **Data filtering and searching**: Processing user queries and returning filtered results

Backend components enable a seamless request-response cycle where HTMX sends requests to these views, which process data on the server and return HTML fragments to update the UI.

## Architecture

### Router Registration System

Backend components use the router system from `registries.route_registry` for clean, centralized route management:

```python
from registries.route_registry import router

@router.register(
    path="components/search-objects/<int:content_type_id>/",
    name="components_search_objects",
)
def search_objects(request: HttpRequest, content_type_id: int) -> HttpResponse:
    # Component logic here
    return render(request, 'components/objects/search_results.html', context)
```

**Key benefits:**
- Centralized route registration
- Consistent naming convention (all component routes prefixed with `components/`)
- Type hints support for URL parameters
- Automatic URL generation for templates

### Component Types

Backend components typically fall into these categories:

1. **Data View Components** - Display and manage data (tables, kanban, calendar)
2. **CRUD Components** - Create, read, update, delete operations
3. **Search/Filter Components** - Find and filter data
4. **Action Components** - Execute operations and return results

## Creating Backend Components

### Basic Component Example

```python
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render, get_object_or_404
from django.contrib.contenttypes.models import ContentType
from registries.route_registry import router

@router.register(
    path="components/permissions-table/",
    name="components_permissions_table",
)
def permissions_table(request: HttpRequest) -> HttpResponse:
    """Renders a table of permissions for the current user.
    
    Args:
        request: The HTTP request object
        
    Returns:
        HttpResponse: Rendered HTML template
    """
    # Fetch data from database
    permissions = get_user_permissions(request.user)
    
    # Build context for template
    context = {
        'permissions': permissions,
        'user': request.user,
    }
    
    # Render and return HTML
    return render(
        request,
        "components/permissions_table.html",
        context
    )
```

### Data View Component Example

```python
@router.register(
    path="components/data_view/<int:content_type_id>/",
    name="components_data_view",
)
def data_view(request: HttpRequest, content_type_id: int) -> HttpResponse:
    """Main data view component that renders tables, kanban, calendar, etc.
    
    Args:
        request: The HTTP request object
        content_type_id: Django ContentType ID for the model
        
    Returns:
        HttpResponse: Rendered data view template
    """
    # Get the model class from content type
    content_type = get_object_or_404(ContentType, id=content_type_id)
    model_class = content_type.model_class()
    
    # Get user's view preference (table, kanban, calendar, etc.)
    preference = get_user_list_view_preference(request.user, content_type_id)
    
    # Get filtered queryset
    queryset = get_queryset_for_user(request.user, model_class)
    
    # Apply filters and search
    if search_query := request.GET.get('search'):
        queryset = string_search_on_queryset(queryset, search_query)
    
    # Apply user filters
    queryset = filter_model(queryset, request.GET)
    
    # Get view-specific context (pagination, kanban groups, calendar events, etc.)
    view_context = _get_extra_context_for_view_type(preference, queryset, request)
    
    # Build final context
    context = {
        'content_type_id': content_type_id,
        'model_class': model_class,
        'queryset': queryset,
        'preference': preference,
        **view_context,
    }
    
    return render(request, "components/objects/dataview.html", context)
```

### CRUD Component Example

```python
@router.register(
    path="components/create-object/<int:content_type_id>/",
    name="components_create_object",
)
def create_object(request: HttpRequest, content_type_id: int) -> HttpResponse:
    """Creates a new object and returns the create form.
    
    Args:
        request: The HTTP request object
        content_type_id: Django ContentType ID for the model
        
    Returns:
        HttpResponse: Rendered create form or success response
    """
    content_type = get_object_or_404(ContentType, id=content_type_id)
    model_class = content_type.model_class()
    
    # Check permissions
    if not request.user.has_perm(f'{model_class._meta.app_label}.add_{model_class._meta.model_name}'):
        return HttpResponse("Permission denied", status=403)
    
    # Create the form
    ModelForm = modelform_factory(
        model_class,
        form=BloomerpModelForm,
        fields="__all__",
    )
    
    if request.method == "GET":
        # Display the form
        form = ModelForm(model=model_class, user=request.user)
        return render_blank_form(request, form)
    
    elif request.method == "POST":
        # Process form submission
        form = ModelForm(request.POST, model=model_class, user=request.user)
        if form.is_valid():
            instance = form.save()
            context = {'object': instance, 'success': True}
            return render(request, "components/objects/create_success.html", context)
        else:
            return render_blank_form(request, form)
```

### Search/Filter Component Example

```python
@router.register(
    path="components/search-objects/<int:content_type_id>/",
    name="components_search_objects",
)
def search_objects(request: HttpRequest, content_type_id: int) -> HttpResponse:
    """Searches for objects and returns matching results.
    
    Args:
        request: The HTTP request object
        content_type_id: Django ContentType ID for the model
        
    Returns:
        HttpResponse: Rendered search results
    """
    model_class = ContentType.objects.get_for_id(content_type_id).model_class()
    
    # Get search parameters from query string
    query = request.GET.get('fk_search_results_query', '').strip()
    field_name = request.GET.get('field_name', '')
    search_type = request.GET.get('search_type', 'fk')
    
    # Validate search type
    if search_type not in ['fk', 'm2m']:
        return HttpResponse("Invalid search type", status=400)
    
    # Perform search
    if query:
        # Use model's string_search method if available
        if hasattr(model_class, 'string_search'):
            objects = model_class.string_search(query)[:5]
        else:
            objects = model_class.objects.filter(name__icontains=query)[:5]
    else:
        # Return first 5 objects if no query
        objects = model_class.objects.all()[:5]
    
    # Build context
    context = {
        'objects': objects,
        'field_name': field_name,
        'search_type': search_type,
    }
    
    return render(request, 'components/objects/search_results.html', context)
```

## HTMX Integration

Backend components work seamlessly with HTMX. Here's how:

### Triggering a Component via HTMX

```html
<!-- Load a data view when page loads -->
<div hx-get="{% url 'components_data_view' content_type_id %}"
     hx-trigger="load"
     hx-swap="outerHTML">
    Loading...
</div>

<!-- Search on input -->
<input type="text"
       hx-get="{% url 'components_search_objects' content_type_id %}"
       hx-trigger="keyup changed delay:500ms"
       name="fk_search_results_query"
       hx-swap="outerHTML">

<!-- Create object on button click -->
<button hx-get="{% url 'components_create_object' content_type_id %}"
        hx-target="#form-container"
        hx-swap="outerHTML">
    New Object
</button>
```

### Response Behavior

**For GET requests:** Return a rendered HTML fragment that will be swapped into the DOM.

```python
return render(request, 'components/my_component.html', context)
```

**For POST requests:** Return either:
- Updated HTML fragment (success)
- Form with errors (validation failure)
- Error response (permission denied, etc.)

```python
if form.is_valid():
    instance = form.save()
    return render(request, 'components/success.html', {'object': instance})
else:
    return render(request, 'components/form.html', {'form': form})
```

**Triggering events after swap:**

```python
# Return response with HX-Trigger header
response = render(request, 'components/success.html', context)
response['HX-Trigger'] = 'dataUpdated,formClosed'
return response
```

## Best Practices

### 1. Always Check Permissions

Use Django's permission system to ensure users can access the data:

```python
def my_component(request: HttpRequest) -> HttpResponse:
    # Check if user has permission
    if not request.user.has_perm('app.view_model'):
        return HttpResponse("Permission denied", status=403)
    
    # Continue with component logic
```

### 2. Use get_object_or_404

Always use `get_object_or_404` for retrieving objects by ID:

```python
from django.shortcuts import get_object_or_404

content_type = get_object_or_404(ContentType, id=content_type_id)
```

### 3. Filter Querysets by User

Always apply user-specific filters to querysets:

```python
queryset = get_queryset_for_user(request.user, model_class)
```

### 4. Handle Invalid Input Gracefully

Validate and sanitize all user input:

```python
search_query = request.GET.get('query', '').strip()
if not search_query:
    return HttpResponse("Search query required", status=400)

try:
    page = int(request.GET.get('page', 1))
except ValueError:
    page = 1
```

### 5. Build Meaningful Context

Provide all necessary data for the template:

```python
context = {
    'objects': objects,
    'page': page,
    'total_count': total_count,
    'has_next': has_next,
    'field_name': field_name,
}
```

### 6. Use Consistent Naming

Follow naming conventions for component routes and templates:

- Routes: `components/<resource>/<action>/`
- Templates: `components/<resource>/<action>.html`
- Examples:
  - `components/search-objects/` → `components/objects/search_results.html`
  - `components/create-object/` → `components/objects/create.html`
  - `components/data-view/` → `components/objects/dataview.html`

### 7. Return Appropriate HTTP Status Codes

Use proper status codes for different scenarios:

```python
if not request.user.has_perm(...):
    return HttpResponse("Permission denied", status=403)

if not object_exists:
    return HttpResponse("Not found", status=404)

if form.is_valid():
    return render(request, 'success.html', context)  # 200 (default)
else:
    return render(request, 'form.html', {'form': form})  # 200
```

### 8. Separate Helper Functions

Extract complex logic into helper functions:

```python
def _get_extra_context_for_view_type(preference, queryset, request) -> dict:
    """Returns context specific to the view type (table, kanban, calendar)."""
    context = {}
    
    if preference.view_type == ViewType.TABLE:
        pass
    elif preference.view_type == ViewType.KANBAN:
        context['kanban_groups'] = _build_kanban_groups(queryset, preference.kanban_group_by_field)
    elif preference.view_type == ViewType.CALENDAR:
        context.update(_build_calendar_context(preference, queryset, request))
    
    return context


def _build_kanban_groups(queryset, group_by_field) -> list:
    """Builds kanban groups from a queryset."""
    # Implementation here
    return groups
```

## Migration from Old System

If your component uses the old URL configuration system, migrate it to the router:

### Before (Old System)

```python
# In urls.py
urlpatterns = [
    path('components/my-component/', views.my_component, name='components_my_component'),
]

# In views.py
def my_component(request):
    # Component logic
    pass
```

### After (Router System)

```python
# In components/my_component.py
from registries.route_registry import router

@router.register(
    path="components/my-component/",
    name="components_my_component",
)
def my_component(request: HttpRequest) -> HttpResponse:
    # Component logic
    return render(request, 'components/my_component.html', context)
```

**Benefits of migration:**
- Routes are co-located with their components
- Automatic URL registration (no manual urls.py updates)
- Consistent naming and structure
- Easier to discover and maintain components
- Centralized component definitions

## Common Patterns

### Pattern: Pagination

```python
def my_component(request: HttpRequest) -> HttpResponse:
    page = request.GET.get('page', 1)
    
    try:
        page = int(page)
    except ValueError:
        page = 1
    
    queryset = MyModel.objects.all()
    paginator = Paginator(queryset, per_page=20)
    
    try:
        page_obj = paginator.page(page)
    except (EmptyPage, PageNotAnInteger):
        page_obj = paginator.page(1)
    
    context = {
        'page_obj': page_obj,
        'paginator': paginator,
    }
    
    return render(request, 'components/my_component.html', context)
```

### Pattern: Inline Editing

```python
@router.register(
    path="components/edit-field/<int:object_id>/<str:field_name>/",
    name="components_edit_field",
)
def edit_field(request: HttpRequest, object_id: int, field_name: str) -> HttpResponse:
    """Edit a single field inline."""
    obj = get_object_or_404(MyModel, id=object_id)
    
    if request.method == "POST":
        value = request.POST.get('value')
        setattr(obj, field_name, value)
        obj.save()
        return render(request, 'components/field_display.html', {'object': obj, 'field': field_name})
    
    context = {'object': obj, 'field_name': field_name}
    return render(request, 'components/edit_field.html', context)
```

### Pattern: Filtering with Multiple Criteria

```python
def filtered_objects(request: HttpRequest, content_type_id: int) -> HttpResponse:
    """Display objects filtered by multiple criteria."""
    content_type = get_object_or_404(ContentType, id=content_type_id)
    model_class = content_type.model_class()
    
    # Start with base queryset
    queryset = get_queryset_for_user(request.user, model_class)
    
    # Apply filters
    queryset = filter_model(queryset, request.GET)
    
    # Apply search
    if search := request.GET.get('search'):
        queryset = string_search_on_queryset(queryset, search)
    
    # Order results
    order_by = request.GET.get('order_by', '-created_at')
    queryset = queryset.order_by(order_by)
    
    context = {
        'objects': queryset,
        'total_count': queryset.count(),
    }
    
    return render(request, 'components/filtered_list.html', context)
```
```