# @bloomerp/frontend

Public TypeScript component API for Bloomerp implementation apps. Requires a
Bloomerp release with frontend-extension support. Package versions follow the
Python release; use the same version in your app and deployment.

```typescript
import { BaseComponent, registerComponent } from '@bloomerp/frontend';

class Planner extends BaseComponent {
    /** Render this planner after the registry has stored its instance. */
    public override initialize(): void {
        this.element?.setAttribute('data-planner-ready', 'true');
    }
}

registerComponent('customer:planner', Planner);
```

Use `<div bloomerp-component="customer:planner"></div>` in your Django template.
Override `destroy()` to release resources and `onAfterSwap()` to refresh references
after HTMX changes child content. Constructors must not call `initialize()`.

**Externalize `@bloomerp/frontend` in your implementation's Vite/Rollup build.**
Exclude it from Vite dependency optimization too. The CLI scaffolds both settings.
Django installs an import map pointing this name (and the package's fallback
`@bloomerp/runtime` import) to the core public module. This keeps registration and
instance lookup in the same registry as the framework. Do not bundle framework
source files or initialize a second component lifecycle.

Build from the repository with `npm install && npm run build`. Declarations are
generated from the actual core component implementation. The published package
contains only its runtime facade and declarations, without framework dependencies.
