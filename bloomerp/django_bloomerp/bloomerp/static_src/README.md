# TypeScript + Vite Setup for Bloomerp

This document explains the modern JavaScript/TypeScript development setup for the Bloomerp Django project.

## Overview

The project now uses:
- **TypeScript** for type-safe JavaScript development
- **Vite** for fast bundling and hot module replacement (HMR)
- **npm** for package management
- **HTMX event listeners** for dynamic content handling

## Project Structure

```
bloomerp/django_bloomerp/bloomerp/
├── static_src/                     # Source files (TypeScript, CSS)
│   ├── package.json               # npm dependencies and scripts
│   ├── tsconfig.json              # TypeScript compiler configuration
│   ├── vite.config.ts             # Vite bundler configuration
│   ├── postcss.config.js          # PostCSS configuration (for Tailwind)
│   ├── tailwind.config.js         # Tailwind CSS configuration
│   ├── src/
│   │   └── styles.css             # Tailwind CSS source
│   └── ts/                        # TypeScript source files
│       ├── main.ts                # Main entry point
│       ├── types/                 # TypeScript type definitions
│       │   ├── htmx.d.ts          # HTMX type definitions
│       │   └── bloomerp.d.ts      # Bloomerp-specific types
│       └── modules/               # Feature modules
│           └── datatable.ts       # DataTable module example
│
└── static/bloomerp/               # Compiled/built files (Django serves these)
    ├── css/dist/
    │   └── styles.css             # Built Tailwind CSS
    └── js/
        ├── dist/                  # Built TypeScript bundles
        │   ├── main.js            # Main bundle
        │   └── manifest.json      # Vite manifest
        ├── datatable.js           # Legacy JS (to be migrated)
        ├── main.js                # Legacy JS (to be migrated)
        └── ...                    # Other legacy JS files
```

## Installation

### Prerequisites
- Node.js 18+ and npm
- Python 3.x with Django

### Setup

1. **Navigate to static_src directory:**
   ```bash
   cd bloomerp/django_bloomerp/bloomerp/static_src
   ```

2. **Install npm dependencies:**
   ```bash
   npm install
   ```

## Development Workflow

### Running in Development Mode

You need to run **two** processes simultaneously:

#### Terminal 1: Vite Dev Server (TypeScript + HMR)
```bash
cd bloomerp/django_bloomerp/bloomerp/static_src
npm run dev:js
```
This starts the Vite dev server on `http://localhost:5173` with hot module replacement.

#### Terminal 2: Tailwind CSS Watch
```bash
cd bloomerp/django_bloomerp/bloomerp/static_src
npm run dev:css
```
This watches and rebuilds Tailwind CSS on file changes.

#### Terminal 3: Django Development Server
```bash
cd bloomerp/django_bloomerp
python manage.py runserver
```

**Or run both CSS and JS together:**
```bash
cd bloomerp/django_bloomerp/bloomerp/static_src
npm run dev
```
This uses `concurrently` to run both dev:css and dev:js together.

### Building for Production

Build all assets for production:
```bash
cd bloomerp/django_bloomerp/bloomerp/static_src
npm run build
```

This will:
1. Clean previous builds
2. Build and minify Tailwind CSS → `../static/css/dist/styles.css`
3. Compile and bundle TypeScript → `../static/bloomerp/js/dist/main.js`

## How It Works

### TypeScript Entry Point

`static_src/ts/main.ts` is the main entry point that:
1. Initializes the Bloomerp application
2. Sets up HTMX event listeners for dynamic content
3. Auto-discovers and initializes components (datatables, etc.)

### HTMX Event Listeners

The TypeScript code listens to HTMX events to handle dynamically loaded content:

```typescript
// Fired when HTMX loads content (initial or swapped)
document.body.addEventListener('htmx:load', (event) => {
  // Reinitialize components in loaded content
});

// Fired after HTMX swaps content into DOM
document.body.addEventListener('htmx:afterSwap', (event) => {
  // Reinitialize components in swapped content
});
```

This means you don't need `document.addEventListener('DOMContentLoaded', ...)` for HTMX-loaded content.

### Example: DataTable Module

The datatable module (`static_src/ts/modules/datatable.ts`) demonstrates:

1. **TypeScript class with type safety:**
   ```typescript
   export class DataTable {
     private tableId: string;
     private table: HTMLElement | null = null;
     
     constructor(config: DataTableConfig) {
       this.tableId = config.tableId;
       this.initialize();
     }
   }
   ```

2. **HTMX integration:**
   - Tables are automatically discovered via `[data-datatable]` attribute
   - Reinitialized after HTMX swaps content
   - Uses `window.htmx.ajax()` for dynamic reloads

3. **Context menu with event delegation:**
   - Right-click on table cells
   - Copy cell values
   - Filter by cell values

### Template Integration

Templates now include the bundled JavaScript:

**`templates/bloomerp_base.html`:**
```django
<!-- TypeScript Bundle (Vite) -->
{% include 'snippets/vite_bundle.html' %}
```

**`templates/snippets/vite_bundle.html`:**
- In DEBUG mode: Loads from Vite dev server with HMR
- In production: Loads from built static files

## Adding New TypeScript Modules

### 1. Create a new module

Create `static_src/ts/modules/mymodule.ts`:

```typescript
export class MyModule {
  constructor() {
    console.log('MyModule initialized');
  }
  
  public doSomething(): void {
    // Your code here
  }
}
```

### 2. Import in main.ts

Edit `static_src/ts/main.ts`:

```typescript
import { MyModule } from './modules/mymodule';

class BloomerpApp {
  private myModule: MyModule;
  
  private initializeComponents(): void {
    this.myModule = new MyModule();
    // ... other initializations
  }
}
```

### 3. Add HTMX event listener if needed

If your module needs to handle dynamically loaded content:

```typescript
private onHtmxAfterSwap(event: CustomEvent): void {
  const target = event.detail?.target as HTMLElement;
  
  // Reinitialize your module for new content
  this.myModule.reinitialize(target);
}
```

## Installing npm Packages

Install any npm package and use it in your TypeScript:

```bash
cd bloomerp/django_bloomerp/bloomerp/static_src
npm install lodash-es
npm install --save-dev @types/lodash-es
```

Then use in your TypeScript:

```typescript
import { debounce } from 'lodash-es';

const debouncedSearch = debounce((query: string) => {
  // Search logic
}, 300);
```

Vite will automatically bundle it into your output.

## TypeScript Configuration

### `tsconfig.json`

Key settings:
- `target: "ES2020"` - Modern JavaScript output
- `module: "ESNext"` - ES modules
- `strict: false` - Relaxed type checking (can be enabled later)
- `lib: ["ES2020", "DOM"]` - Browser APIs available
- Path alias: `@/*` → `./ts/*` for clean imports

### `vite.config.ts`

Key settings:
- Input: `ts/main.ts`
- Output: `../static/bloomerp/js/dist/`
- Dev server: `localhost:5173` with HMR
- Source maps enabled for debugging
- ES2020 target for modern browsers

## Debugging

### Development Mode

1. Open browser DevTools
2. Sources tab shows original TypeScript files (via source maps)
3. Set breakpoints directly in TypeScript
4. Console logs show file and line numbers

### Access App Instance

In browser console:

```javascript
// Access the app instance
window.BloomerpApp

// Get a specific datatable
window.BloomerpApp.getDataTable('my-table-id')

// Create a new datatable programmatically
window.BloomerpApp.createDataTable({ tableId: 'my-table' })
```

## Migration Strategy

The setup supports gradual migration from legacy JavaScript:

1. **Phase 1** (Current): 
   - TypeScript bundle loaded alongside legacy JS
   - Datatable migrated to TypeScript as example
   - Both old and new code coexist

2. **Phase 2**: 
   - Migrate other modules (forms, modals, etc.)
   - Update imports in main.ts

3. **Phase 3**: 
   - Remove legacy JS files
   - All functionality in TypeScript

## npm Scripts Reference

```bash
npm run dev          # Run both CSS and JS dev servers
npm run dev:css      # Watch and rebuild Tailwind CSS
npm run dev:js       # Start Vite dev server with HMR
npm run build        # Build everything for production
npm run build:css    # Build Tailwind CSS for production
npm run build:js     # Build TypeScript bundle for production
npm run type-check   # Check TypeScript types without building
npm run preview      # Preview production build
```

## Troubleshooting

### Vite dev server connection issues

If you see errors about connecting to `localhost:5173`:
1. Make sure `npm run dev:js` is running
2. Check that port 5173 is not blocked
3. Verify Django DEBUG=True in settings

### TypeScript errors

Run type checking:
```bash
npm run type-check
```

### HTMX events not firing

1. Check browser console for errors
2. Verify HTMX is loaded (CDN or local)
3. Check that elements have proper HTMX attributes
4. Use HTMX browser extension for debugging

### Module not found errors

1. Clear node_modules and reinstall:
   ```bash
   rm -rf node_modules package-lock.json
   npm install
   ```

2. Check that paths in `tsconfig.json` are correct

## Best Practices

1. **Type your data structures** - Create interfaces in `ts/types/`
2. **Use HTMX events** - Don't rely on DOMContentLoaded for dynamic content
3. **Keep modules focused** - One concern per module
4. **Export what's needed** - Make functions/classes available to other modules
5. **Document complex logic** - Add JSDoc comments for better IDE support
6. **Test in development mode** - Use HMR for faster iteration
7. **Build before deploy** - Always run `npm run build` before deploying

## Resources

- [Vite Documentation](https://vitejs.dev/)
- [TypeScript Documentation](https://www.typescriptlang.org/docs/)
- [HTMX Documentation](https://htmx.org/docs/)
- [Django Static Files](https://docs.djangoproject.com/en/stable/howto/static-files/)
