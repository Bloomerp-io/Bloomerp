# Example: Using TypeScript with HTMX in Bloomerp

This document provides a practical example of how the new TypeScript setup works with HTMX in the Bloomerp Django project.

## Example 1: DataTable with Context Menu

The datatable component demonstrates the complete TypeScript + HTMX workflow.

### Django Template (HTML)

```django
{% comment %}
File: templates/snippets/datatable.html
{% endcomment %}

<!-- The table has data-datatable attribute for TypeScript auto-discovery -->
<table class="table table-hover" id="my-products-table" data-datatable>
  <thead>
    <tr>
      <th>Product Name</th>
      <th>Price</th>
      <th>Status</th>
    </tr>
  </thead>
  <tbody>
    {% for product in products %}
    <tr>
      <!-- Cells with allow-context-menu enable right-click menu -->
      <td allow-context-menu
          data-value="{{ product.name }}"
          data-object-id="{{ product.id }}"
          data-context-menu-filter-value="name={{ product.name }}">
        {{ product.name }}
      </td>
      <td allow-context-menu
          data-value="{{ product.price }}"
          data-object-id="{{ product.id }}">
        ${{ product.price }}
      </td>
      <td allow-context-menu
          data-value="{{ product.status }}"
          data-object-id="{{ product.id }}"
          data-context-menu-filter-value="status={{ product.status }}">
        {{ product.status }}
      </td>
    </tr>
    {% endfor %}
  </tbody>
</table>

<!-- Hidden input stores the URL for HTMX reloads -->
<input type="hidden" 
       id="my-products-table-datatable-url" 
       value="{% url 'components_datatable' %}?content_type_id={{ content_type.id }}">

<!-- Context menu (shown on right-click) -->
<div id="my-products-table-context-menu" 
     class="context-menu" 
     style="display: none; position: absolute;">
  <ul>
    <li id="my-products-table-context-menu-copy-value">
      <i class="bi bi-clipboard"></i> Copy Value
    </li>
    <li id="my-products-table-context-menu-filter-value-list-item">
      <i class="bi bi-filter"></i> Filter by Value
    </li>
  </ul>
</div>
```

### How It Works

1. **Initial Page Load:**
   - `main.ts` initializes on DOM ready
   - Finds all tables with `[data-datatable]` attribute
   - Creates `DataTable` instance for each table
   - Sets up context menu event listeners

2. **HTMX Content Swap:**
   - User clicks filter or pagination
   - HTMX loads new HTML from server
   - `htmx:afterSwap` event fires
   - TypeScript reinitializes the datatable in the swapped content

3. **User Interactions:**
   - Right-click on cell → shows context menu
   - Click "Copy Value" → copies to clipboard
   - Click "Filter by Value" → triggers HTMX request with filter params

### TypeScript Flow

```typescript
// 1. Auto-initialization (main.ts)
document.body.addEventListener('htmx:afterSwap', (event) => {
  const target = event.detail?.target;
  // Find datatables in swapped content
  const tables = target.querySelectorAll('[data-datatable]');
  tables.forEach(table => {
    new DataTable({ tableId: table.id });
  });
});

// 2. DataTable class (modules/datatable.ts)
export class DataTable {
  constructor(config) {
    this.tableId = config.tableId;
    this.initialize();
  }
  
  private initialize() {
    // Set up context menu on cells with allow-context-menu
    const cells = this.table.querySelectorAll('td[allow-context-menu]');
    cells.forEach(cell => {
      cell.addEventListener('contextmenu', (e) => {
        this.showContextMenu(cell, e);
      });
    });
  }
  
  public reload(params?: string) {
    // Use HTMX to reload table
    window.htmx.ajax('GET', `${url}?${params}`, `#${this.tableId}`);
  }
}
```

## Example 2: Custom HTMX Component with TypeScript

Let's create a new feature: an auto-save form field.

### Step 1: Create TypeScript Module

```typescript
// File: static_src/ts/modules/autosave.ts

export interface AutoSaveConfig {
  fieldId: string;
  saveUrl: string;
  debounceMs?: number;
}

export class AutoSaveField {
  private field: HTMLInputElement | HTMLTextAreaElement | null;
  private saveUrl: string;
  private debounceMs: number;
  private timeoutId: number | null = null;

  constructor(config: AutoSaveConfig) {
    this.field = document.getElementById(config.fieldId) as HTMLInputElement;
    this.saveUrl = config.saveUrl;
    this.debounceMs = config.debounceMs || 500;
    
    if (this.field) {
      this.initialize();
    }
  }

  private initialize(): void {
    if (!this.field) return;
    
    // Listen for input changes
    this.field.addEventListener('input', () => {
      this.handleInput();
    });
    
    // Show saved indicator
    this.field.addEventListener('htmx:afterRequest', () => {
      this.showSavedIndicator();
    });
  }

  private handleInput(): void {
    // Clear existing timeout
    if (this.timeoutId) {
      clearTimeout(this.timeoutId);
    }
    
    // Show saving indicator
    this.showSavingIndicator();
    
    // Debounce the save
    this.timeoutId = window.setTimeout(() => {
      this.save();
    }, this.debounceMs);
  }

  private save(): void {
    if (!this.field) return;
    
    // Use HTMX to save
    window.htmx.ajax('POST', this.saveUrl, {
      values: { value: this.field.value },
      target: `#${this.field.id}-status`,
    });
  }

  private showSavingIndicator(): void {
    const status = document.getElementById(`${this.field!.id}-status`);
    if (status) {
      status.textContent = 'Saving...';
      status.className = 'text-yellow-500';
    }
  }

  private showSavedIndicator(): void {
    const status = document.getElementById(`${this.field!.id}-status`);
    if (status) {
      status.textContent = 'Saved ✓';
      status.className = 'text-green-500';
      
      // Clear after 2 seconds
      setTimeout(() => {
        status.textContent = '';
      }, 2000);
    }
  }

  public destroy(): void {
    // Cleanup if needed
    if (this.timeoutId) {
      clearTimeout(this.timeoutId);
    }
  }
}

// Auto-discover and initialize autosave fields
export function initAutoSaveFields(): Map<string, AutoSaveField> {
  const fields = new Map<string, AutoSaveField>();
  const elements = document.querySelectorAll<HTMLElement>('[data-autosave]');
  
  elements.forEach(element => {
    const saveUrl = element.dataset.autosaveUrl;
    if (element.id && saveUrl) {
      const field = new AutoSaveField({
        fieldId: element.id,
        saveUrl: saveUrl,
      });
      fields.set(element.id, field);
    }
  });
  
  return fields;
}
```

### Step 2: Add to main.ts

```typescript
// File: static_src/ts/main.ts

import { initAutoSaveFields } from './modules/autosave';

class BloomerpApp {
  private autoSaveFields: Map<string, AutoSaveField> = new Map();
  
  private initializeComponents(): void {
    this.initDataTables();
    this.initAutoSaveFields();  // Add this line
  }
  
  private initAutoSaveFields(): void {
    this.autoSaveFields = initAutoSaveFields();
    console.log(`Initialized ${this.autoSaveFields.size} autosave field(s)`);
  }
  
  private onHtmxAfterSwap(event: CustomEvent): void {
    const target = event.detail?.target as HTMLElement;
    // Reinitialize autosave fields in swapped content
    const fields = target.querySelectorAll('[data-autosave]');
    fields.forEach(field => {
      if (field.id && field.dataset.autosaveUrl) {
        const autoSaveField = new AutoSaveField({
          fieldId: field.id,
          saveUrl: field.dataset.autosaveUrl,
        });
        this.autoSaveFields.set(field.id, autoSaveField);
      }
    });
  }
}
```

### Step 3: Use in Django Template

```django
<div class="form-group">
  <label for="product-description">Description</label>
  <textarea 
    id="product-description"
    name="description"
    class="form-control"
    data-autosave
    data-autosave-url="{% url 'save_field' object.id 'description' %}"
  >{{ object.description }}</textarea>
  <span id="product-description-status" class="text-sm"></span>
</div>
```

### Step 4: Build and Test

```bash
# Rebuild the bundle
npm run build:js

# Or use dev mode for instant updates
npm run dev:js
```

Now when you type in the textarea:
1. TypeScript detects input changes
2. Debounces for 500ms
3. Shows "Saving..." indicator
4. Sends HTMX POST request
5. Shows "Saved ✓" on success

## Example 3: Installing and Using npm Packages

Let's add date formatting using the `date-fns` package.

### Step 1: Install Package

```bash
cd bloomerp/django_bloomerp/bloomerp/static_src
npm install date-fns
```

### Step 2: Create Utility Module

```typescript
// File: static_src/ts/utils/dates.ts

import { format, formatDistance, parseISO } from 'date-fns';

export function formatDate(date: string | Date, pattern: string = 'PPP'): string {
  const dateObj = typeof date === 'string' ? parseISO(date) : date;
  return format(dateObj, pattern);
}

export function timeAgo(date: string | Date): string {
  const dateObj = typeof date === 'string' ? parseISO(date) : date;
  return formatDistance(dateObj, new Date(), { addSuffix: true });
}

// Format all dates on the page with data-date attribute
export function formatAllDates(): void {
  document.querySelectorAll<HTMLElement>('[data-date]').forEach(element => {
    const isoDate = element.dataset.date;
    const formatType = element.dataset.dateFormat || 'PPP';
    
    if (isoDate) {
      if (formatType === 'relative') {
        element.textContent = timeAgo(isoDate);
      } else {
        element.textContent = formatDate(isoDate, formatType);
      }
    }
  });
}
```

### Step 3: Use in main.ts

```typescript
// File: static_src/ts/main.ts

import { formatAllDates } from './utils/dates';

class BloomerpApp {
  private initializeComponents(): void {
    this.initDataTables();
    this.initAutoSaveFields();
    formatAllDates();  // Format dates on initial load
  }
  
  private onHtmxAfterSwap(event: CustomEvent): void {
    // ... existing code ...
    formatAllDates();  // Re-format dates after HTMX swap
  }
}
```

### Step 4: Use in Templates

```django
<!-- ISO date from Django -->
<span data-date="{{ object.created_at|date:'c' }}" 
      data-date-format="PPP">
  {{ object.created_at }}
</span>

<!-- Relative time -->
<span data-date="{{ object.updated_at|date:'c' }}" 
      data-date-format="relative">
  {{ object.updated_at }}
</span>
```

Result:
- First span: "November 19, 2025"
- Second span: "2 hours ago"

## Example 4: Global Access for Console Debugging

The app instance is globally accessible for debugging:

```javascript
// In browser console:

// Get the app
window.BloomerpApp

// Get all datatables
window.BloomerpApp.dataTables

// Get specific datatable
const table = window.BloomerpApp.getDataTable('my-products-table')

// Reload a table programmatically
table.reload('status=active')

// Filter a table
table.filter('category=electronics')

// Create a new datatable on the fly
window.BloomerpApp.createDataTable({
  tableId: 'dynamic-table'
})
```

## Key Patterns

### 1. Data Attributes for Configuration

```html
<div data-component="mycomponent" 
     data-option1="value1"
     data-option2="value2">
```

```typescript
const config = {
  option1: element.dataset.option1,
  option2: element.dataset.option2,
};
```

### 2. HTMX Event Listeners

```typescript
// Listen to HTMX events
document.body.addEventListener('htmx:afterSwap', (event) => {
  const target = event.detail?.target;
  reinitializeComponents(target);
});

// Trigger HTMX requests from TypeScript
window.htmx.ajax('GET', '/api/data', '#target-element');
```

### 3. Auto-Discovery Pattern

```typescript
export function initAllComponents(): Map<string, Component> {
  const components = new Map();
  const elements = document.querySelectorAll('[data-component]');
  
  elements.forEach(element => {
    if (element.id) {
      const component = new Component({ elementId: element.id });
      components.set(element.id, component);
    }
  });
  
  return components;
}
```

### 4. Cleanup Pattern

```typescript
export class Component {
  private cleanup: (() => void)[] = [];
  
  private initialize(): void {
    const handler = () => { /* ... */ };
    element.addEventListener('click', handler);
    
    // Store cleanup function
    this.cleanup.push(() => {
      element.removeEventListener('click', handler);
    });
  }
  
  public destroy(): void {
    this.cleanup.forEach(fn => fn());
    this.cleanup = [];
  }
}
```

## Summary

The TypeScript + Vite + HTMX setup provides:

1. ✅ **Type safety** - Catch errors at compile time
2. ✅ **npm packages** - Use any package from npm registry
3. ✅ **Fast development** - HMR updates code instantly
4. ✅ **HTMX integration** - Seamless server-rendered HTML updates
5. ✅ **Modular code** - Organize by feature, not file type
6. ✅ **Debugging** - Source maps for browser DevTools
7. ✅ **Production builds** - Minified, optimized bundles

Start with the datatable example, then gradually migrate other features to TypeScript!
