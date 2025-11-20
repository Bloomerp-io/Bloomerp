# Migration Guide: JavaScript to TypeScript

This guide helps you convert existing JavaScript files to TypeScript incrementally.

## Migration Strategy

### Phase 1: Side-by-side (Current)
- TypeScript bundle loads alongside legacy JS
- New features written in TypeScript
- Old code continues to work

### Phase 2: Incremental migration
- Convert one module at a time
- Test thoroughly after each conversion
- Update imports and references

### Phase 3: Complete TypeScript
- Remove all legacy JS files
- Everything runs through TypeScript
- Full type safety

## Step-by-Step Migration Process

### Example: Migrating messages.js

**Current file:** `static/bloomerp/js/messages.js`

```javascript
// Original JavaScript
function showMessage(message, type) {
    // Create message element
    const messageDiv = document.createElement('div');
    messageDiv.className = `alert alert-${type}`;
    messageDiv.textContent = message;
    
    // Add to DOM
    document.body.appendChild(messageDiv);
    
    // Remove after 3 seconds
    setTimeout(() => {
        messageDiv.remove();
    }, 3000);
}
```

### Step 1: Create TypeScript file

Create `static_src/ts/modules/messages.ts`:

```typescript
// Step 1: Basic conversion with types
export interface MessageOptions {
  message: string;
  type: 'success' | 'info' | 'warning' | 'error';
  duration?: number;
}

export function showMessage(
  message: string, 
  type: 'success' | 'info' | 'warning' | 'error',
  duration: number = 3000
): void {
  // Create message element
  const messageDiv = document.createElement('div');
  messageDiv.className = `alert alert-${type}`;
  messageDiv.textContent = message;
  
  // Add to DOM
  document.body.appendChild(messageDiv);
  
  // Remove after duration
  setTimeout(() => {
    messageDiv.remove();
  }, duration);
}

// Alternative: Class-based approach
export class MessageService {
  private container: HTMLElement;
  
  constructor(containerId: string = 'message-container') {
    this.container = this.getOrCreateContainer(containerId);
  }
  
  private getOrCreateContainer(id: string): HTMLElement {
    let container = document.getElementById(id);
    if (!container) {
      container = document.createElement('div');
      container.id = id;
      container.className = 'message-container';
      document.body.appendChild(container);
    }
    return container;
  }
  
  public show(options: MessageOptions): void {
    const { message, type, duration = 3000 } = options;
    
    const messageDiv = document.createElement('div');
    messageDiv.className = `alert alert-${type} fade-in`;
    messageDiv.textContent = message;
    
    this.container.appendChild(messageDiv);
    
    setTimeout(() => {
      messageDiv.classList.add('fade-out');
      setTimeout(() => messageDiv.remove(), 300);
    }, duration);
  }
  
  public success(message: string, duration?: number): void {
    this.show({ message, type: 'success', duration });
  }
  
  public error(message: string, duration?: number): void {
    this.show({ message, type: 'error', duration });
  }
  
  public info(message: string, duration?: number): void {
    this.show({ message, type: 'info', duration });
  }
  
  public warning(message: string, duration?: number): void {
    this.show({ message, type: 'warning', duration });
  }
  
  public clear(): void {
    this.container.innerHTML = '';
  }
}
```

### Step 2: Export from main.ts

Update `static_src/ts/main.ts`:

```typescript
import { MessageService, showMessage } from './modules/messages';

class BloomerpApp {
  public messages: MessageService;
  
  constructor() {
    this.messages = new MessageService();
    this.setupHtmxEventListeners();
    this.init();
    
    // Make functions globally available for backward compatibility
    this.exposeGlobalFunctions();
  }
  
  private exposeGlobalFunctions(): void {
    // Legacy function for backward compatibility
    (window as any).showMessage = (msg: string, type: string) => {
      this.messages.show({ 
        message: msg, 
        type: type as any 
      });
    };
  }
}
```

### Step 3: Build and test

```bash
npm run build:js
```

Test in browser:

```javascript
// Old way still works (backward compatible)
showMessage('Hello', 'success');

// New way with TypeScript
window.BloomerpApp.messages.success('Hello!');
```

### Step 4: Remove legacy JS

Once confident, remove from `bloomerp_base.html`:

```django
<!-- Remove this line: -->
<!-- <script src="{% static 'bloomerp/js/messages.js' %}"></script> -->
```

And delete the old file:

```bash
rm bloomerp/django_bloomerp/bloomerp/static/bloomerp/js/messages.js
```

## Common Conversion Patterns

### Pattern 1: Global Function → Exported Function

**Before (JS):**
```javascript
function myFunction(param) {
  return param.toUpperCase();
}
```

**After (TS):**
```typescript
export function myFunction(param: string): string {
  return param.toUpperCase();
}

// Make globally available if needed
(window as any).myFunction = myFunction;
```

### Pattern 2: Implicit Types → Explicit Types

**Before (JS):**
```javascript
function calculate(a, b, operation) {
  switch(operation) {
    case 'add': return a + b;
    case 'multiply': return a * b;
    default: return 0;
  }
}
```

**After (TS):**
```typescript
type Operation = 'add' | 'multiply';

export function calculate(
  a: number, 
  b: number, 
  operation: Operation
): number {
  switch(operation) {
    case 'add': return a + b;
    case 'multiply': return a * b;
    default: return 0;
  }
}
```

### Pattern 3: Plain Object → Interface/Type

**Before (JS):**
```javascript
function createUser(name, email, role) {
  return {
    name: name,
    email: email,
    role: role,
    createdAt: new Date()
  };
}
```

**After (TS):**
```typescript
export interface User {
  name: string;
  email: string;
  role: 'admin' | 'user' | 'guest';
  createdAt: Date;
}

export function createUser(
  name: string, 
  email: string, 
  role: User['role']
): User {
  return {
    name,
    email,
    role,
    createdAt: new Date()
  };
}
```

### Pattern 4: Class Conversion

**Before (JS):**
```javascript
class Modal {
  constructor(id) {
    this.id = id;
    this.element = document.getElementById(id);
  }
  
  open() {
    this.element.classList.add('show');
  }
  
  close() {
    this.element.classList.remove('show');
  }
}
```

**After (TS):**
```typescript
export interface ModalConfig {
  id: string;
  closeOnBackdrop?: boolean;
  closeOnEscape?: boolean;
}

export class Modal {
  private id: string;
  private element: HTMLElement | null;
  private config: ModalConfig;
  
  constructor(config: ModalConfig) {
    this.id = config.id;
    this.config = config;
    this.element = document.getElementById(this.id);
    
    if (!this.element) {
      console.error(`Modal element with id "${this.id}" not found`);
    }
    
    this.setupEventListeners();
  }
  
  private setupEventListeners(): void {
    if (this.config.closeOnEscape) {
      document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') this.close();
      });
    }
  }
  
  public open(): void {
    if (this.element) {
      this.element.classList.add('show');
    }
  }
  
  public close(): void {
    if (this.element) {
      this.element.classList.remove('show');
    }
  }
}
```

### Pattern 5: DOM Event Handlers

**Before (JS):**
```javascript
document.getElementById('submit-btn').addEventListener('click', function(e) {
  e.preventDefault();
  const formData = new FormData(document.getElementById('myform'));
  // ... submit logic
});
```

**After (TS):**
```typescript
export class FormHandler {
  private form: HTMLFormElement | null;
  private submitButton: HTMLButtonElement | null;
  
  constructor(formId: string) {
    this.form = document.getElementById(formId) as HTMLFormElement;
    this.submitButton = this.form?.querySelector('[type="submit"]') as HTMLButtonElement;
    
    this.setupEventListeners();
  }
  
  private setupEventListeners(): void {
    this.submitButton?.addEventListener('click', (e: MouseEvent) => {
      e.preventDefault();
      this.handleSubmit();
    });
  }
  
  private handleSubmit(): void {
    if (!this.form) return;
    
    const formData = new FormData(this.form);
    // ... submit logic with type safety
  }
}
```

## Handling Legacy Dependencies

### jQuery Usage

If you're using jQuery and want to keep it:

```bash
npm install jquery
npm install --save-dev @types/jquery
```

Then in TypeScript:

```typescript
import $ from 'jquery';

export function myFunction(): void {
  $('#myElement').fadeIn();
}
```

Or use without types:

```typescript
declare const $: any;

export function myFunction(): void {
  $('#myElement').fadeIn();
}
```

### Global Variables

For global variables from CDN libraries:

```typescript
// Create a declarations file
// File: static_src/ts/types/globals.d.ts

declare global {
  interface Window {
    Alpine: any;
    htmx: HtmxApi;
    showMessage: (msg: string, type: string) => void;
  }
  
  const Alpine: any;
  const htmx: HtmxApi;
}

export {};
```

## Testing Migrated Code

### 1. Type Check

```bash
npm run type-check
```

Fix any errors before building.

### 2. Build

```bash
npm run build:js
```

Verify no build errors.

### 3. Browser Testing

1. Load page in browser
2. Open DevTools console
3. Test migrated functions:

```javascript
// Test the new TypeScript code
window.BloomerpApp.messages.success('Test message');

// Test backward compatibility
showMessage('Legacy test', 'info');
```

4. Check for console errors
5. Test HTMX interactions
6. Verify no regressions

## Migration Checklist

For each file you migrate:

- [ ] Create TypeScript version in `static_src/ts/modules/`
- [ ] Add proper type annotations
- [ ] Create interfaces for complex objects
- [ ] Export functions/classes
- [ ] Import in `main.ts`
- [ ] Add to app initialization
- [ ] Build: `npm run build:js`
- [ ] Test in browser
- [ ] Check backward compatibility
- [ ] Update templates if needed
- [ ] Remove legacy JS file
- [ ] Remove script tag from templates
- [ ] Test again
- [ ] Commit changes

## Priority Order for Migration

Suggested order based on complexity and dependencies:

1. **messages.js** - Simple, no dependencies
2. **modals.js** - Medium complexity
3. **hotkeys.js** - Simple keyboard handlers
4. **bloomerpForms.js** - Complex, many dependencies
5. **files.js** - File upload/management
6. **llm.js** - AI/streaming features
7. **dashboard.js** - Drag/drop complexity
8. **main.js** - Core utilities (last)

## Getting Help

If you encounter issues:

1. Check TypeScript errors: `npm run type-check`
2. Review browser console for runtime errors
3. Use source maps to debug in DevTools
4. Test in both dev and production builds
5. Consult TypeScript handbook: https://www.typescriptlang.org/docs/

## Tips

- ✅ Start with simple, isolated modules
- ✅ Test frequently during migration
- ✅ Keep backward compatibility initially
- ✅ Use `any` type sparingly, but don't let it block you
- ✅ Gradually increase type strictness
- ✅ Document breaking changes
- ✅ Commit after each successful migration
- ❌ Don't migrate everything at once
- ❌ Don't enable strict mode too early
- ❌ Don't break existing functionality
