---
name: bloomerp-components
description: "Create or update Bloomerp TypeScript components, Django component endpoints, fragment templates, and HTMX wiring with the current component lifecycle, central registration, router conventions, permission enforcement, and component tests. Use for work under frontend or backend component directories or markup using bloomerp-component."
---

# Bloomerp Components

Implement the complete component boundary that the task needs: frontend behavior, server endpoint, fragment or Cotton markup, permissions, and tests. Reuse a nearby current component before introducing a new abstraction.

## Workflow

1. Determine whether the change affects TypeScript, a Django endpoint, templates, or multiple layers.
2. Read `references/bloomerp_components_guide.md` for the relevant frontend, backend, HTMX, or testing section.
3. Match component IDs, central TypeScript registration, route `url_name`, template paths, targets, and emitted events end-to-end.
4. Enforce authorization and queryset/field filtering on the server. Use `$bloomerp-permissions` for permission-sensitive behavior.
5. Test the endpoint contract with `BloomerpComponentTestCase`; use an end-to-end test only when browser behavior or HTMX event/swap wiring must be proved.

## Essential Frontend Rules

- Extend `BaseComponent`, or `BaseDataViewComponent` for cell-oriented data views.
- Register component classes centrally in `static_src/ts/main.ts` with `registerComponent(...)`, then use the same ID in `bloomerp-component="..."` markup.
- Do not call `initialize()` from the constructor. The registry instantiates the class, stores it, then calls `initialize()` after class fields are initialized.
- Make `initialize()` safe for the actual element and keep state instance-local.
- Prefer an instance `AbortController` and listener `signal` for grouped cleanup; stored handler references plus `removeEventListener` are also valid. Abort requests, observers, timers, editors, and other owned resources in `destroy()`.
- Override `onAfterSwap()` when an existing component must refresh after swapped child or ancestor content changes.
- Use `getComponent(element)` for lazy instance access and component coordination. Prefer `CustomEvent` for decoupled communication.

## Essential Backend Rules

- Put routed component endpoints in `components/` and register them with `bloomerp.router.router`.
- Use a `components/...` path and an explicit stable `url_name="components_..."`. `name` is human-facing metadata and is not the preferred substitute for a stable reverse name in new code.
- Validate request method and input, use `get_object_or_404` for scoped lookups, and return appropriate fragments, JSON, statuses, redirects, refreshes, and HTMX trigger headers.
- Do not treat markup visibility or router registration as authorization.

## Reference

Read `references/bloomerp_components_guide.md` for lifecycle events, routing choices, Cotton guidance, response helpers, and test patterns.
