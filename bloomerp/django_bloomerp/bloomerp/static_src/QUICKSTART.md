# Quick Start: TypeScript Development Setup

## Initial Setup (One-time)

```bash
# Navigate to static_src
cd bloomerp/django_bloomerp/bloomerp/static_src

# Install dependencies
npm install
```

## Daily Development

### Option 1: Run all dev servers together (Recommended)

```bash
# Terminal 1: Start CSS + JS dev servers
cd bloomerp/django_bloomerp/bloomerp/static_src
npm run dev

# Terminal 2: Start Django
cd bloomerp/django_bloomerp
python manage.py runserver
```

### Option 2: Run servers separately

```bash
# Terminal 1: TypeScript/Vite (Hot Module Replacement)
cd bloomerp/django_bloomerp/bloomerp/static_src
npm run dev:js

# Terminal 2: Tailwind CSS (Watch mode)
cd bloomerp/django_bloomerp/bloomerp/static_src
npm run dev:css

# Terminal 3: Django
cd bloomerp/django_bloomerp
python manage.py runserver
```

## Build for Production

```bash
cd bloomerp/django_bloomerp/bloomerp/static_src
npm run build
```

## Working with the DataTable Example

The datatable component has been migrated to TypeScript as an example.

### In Templates

Add `data-datatable` attribute to tables:

```django
<table id="my-table" data-datatable>
  <!-- ... -->
</table>
```

### In TypeScript

Access datatables programmatically:

```typescript
// Get app instance
const app = window.BloomerpApp;

// Get a specific datatable
const myTable = app.getDataTable('my-table');

// Reload the table
myTable.reload();

// Filter the table
myTable.filter('status=active');
```

### In Browser Console

Debug during development:

```javascript
// Access the app
window.BloomerpApp

// See all datatables
window.BloomerpApp.dataTables

// Trigger HTMX events manually for testing
htmx.ajax('GET', '/some-url', '#target')
```

## Adding a New Feature Module

1. **Create the module:**
   ```bash
   # Create new TypeScript file
   touch bloomerp/django_bloomerp/bloomerp/static_src/ts/modules/myfeature.ts
   ```

2. **Write your module:**
   ```typescript
   // ts/modules/myfeature.ts
   export class MyFeature {
     constructor(element: HTMLElement) {
       this.init(element);
     }
     
     private init(element: HTMLElement): void {
       // Your initialization code
     }
   }
   ```

3. **Import in main.ts:**
   ```typescript
   import { MyFeature } from './modules/myfeature';
   
   // Add to BloomerpApp class initialization
   ```

4. **See changes immediately:**
   - If dev server is running, changes are applied instantly
   - No need to refresh the page (HMR)

## Installing npm Packages

```bash
cd bloomerp/django_bloomerp/bloomerp/static_src

# Install a package
npm install package-name

# Install types (if available)
npm install --save-dev @types/package-name
```

Example with lodash:

```bash
npm install lodash-es
npm install --save-dev @types/lodash-es
```

Then use in TypeScript:

```typescript
import { debounce } from 'lodash-es';

const myFunc = debounce(() => {
  console.log('Debounced!');
}, 300);
```

## Common Tasks

### Check TypeScript errors without building

```bash
npm run type-check
```

### Preview production build locally

```bash
npm run build
npm run preview
```

### Clear and reinstall dependencies

```bash
rm -rf node_modules package-lock.json
npm install
```

## Troubleshooting

### "Cannot connect to Vite dev server"

**Solution:** Make sure `npm run dev:js` is running and Django `DEBUG=True`

### "Module not found" errors

**Solution:** Run `npm install` to install dependencies

### TypeScript errors in editor

**Solution:** 
1. Restart VS Code TypeScript server: `Cmd+Shift+P` → "Restart TS Server"
2. Check `tsconfig.json` is correct
3. Run `npm run type-check` to see all errors

### HTMX content not initializing

**Solution:** Check that your content triggers HTMX events and the TypeScript module listens for them

## Tips

- 🔥 **Hot Module Replacement**: Changes to TypeScript are reflected instantly
- 🎯 **Use browser DevTools**: Set breakpoints in original TypeScript files
- 📝 **Type everything**: Add interfaces for better autocomplete
- 🧪 **Test in console**: Access `window.BloomerpApp` for debugging
- 🔄 **HTMX-first**: Use `htmx:afterSwap` instead of `DOMContentLoaded` for dynamic content

## Next Steps

1. **Migrate more modules**: Convert other JS files to TypeScript
2. **Add types**: Create interfaces for Django model data
3. **Install utilities**: Add packages like date-fns, axios, etc.
4. **Write tests**: Set up Jest or Vitest for unit tests
5. **Enable strict mode**: Once comfortable, enable `"strict": true` in tsconfig.json

## Resources

- Full documentation: `bloomerp/django_bloomerp/bloomerp/static_src/README.md`
- TypeScript handbook: https://www.typescriptlang.org/docs/
- Vite guide: https://vitejs.dev/guide/
- HTMX docs: https://htmx.org/docs/
