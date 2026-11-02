# @bloomerp/frontend

Public TypeScript component API for Bloomerp implementation apps. The built API
ships inside the Python framework distribution; it is not published to npm.
The CLI copies it into each app's generated local dependency and refreshes it
before app wheel builds, keeping declarations aligned with the installed framework.

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
generated from the actual core component implementation. The build writes a
ready-to-install package under `bloomerp/frontend/api` in the Python source tree.
The Python release includes that package, containing only the runtime facade,
declarations, documentation, and package metadata. No npm account is required.

After checking out an app or upgrading Bloomerp, run
`bloomerp app frontend APP_NAME --sync-api` from the project, then run `npm install`
in the app's frontend directory. The generated local copy is excluded from Git.
