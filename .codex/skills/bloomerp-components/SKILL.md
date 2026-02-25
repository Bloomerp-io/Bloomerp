---
name: bloomerp-components
description: "Create and update Bloomerp frontend TypeScript components and backend Django component views with correct lifecycle, router registration, HTMX integration, naming conventions, and permission-aware patterns. Use when implementing or refactoring files under components/ (frontend or backend), adding component routes/templates, or wiring component markup with bloomerp-component attributes."
---

# Bloomerp Components

## Overview
Use this skill to implement Bloomerp UI components end-to-end: frontend component classes (TypeScript) plus backend Django component endpoints and templates. Follow the project's component conventions, router patterns, and HTMX interaction model.

## Quick workflow
1. Determine whether the task is frontend, backend, or both.
2. Reuse existing component patterns before introducing a new abstraction.
3. Implement component logic using the checklists below.
4. Validate route names, template paths, and HTMX behavior.
5. Verify cleanup/lifecycle behavior and permission checks.

## Frontend component implementation checklist
- Subclass `BaseComponent` (or `BaseDataViewComponent` for data-view behavior).
- Register the component with `registerComponent('<component-id>', ComponentClass)`.
- Ensure markup uses `bloomerp-component="<component-id>"`.
- Guard all setup with `if (!this.element) return;`.
- Store event-handler references on the instance for reliable `destroy()` cleanup.
- Keep state instance-local; avoid module-level mutable state.
- Use `data-*` attributes for configuration and parse safely.
- Use `getComponent(element)` for parent-child coordination when needed.
- Keep logic resilient to HTMX-driven reinitialization (`DOMContentLoaded`, `htmx:afterSwap`, history restore, `pageshow`).

## Backend component implementation checklist
- Define route handlers in `components/` modules with `@router.register(...)`.
- Use consistent paths/names:
  - Path prefix: `components/...`
  - Name prefix: `components_...`
- Add type hints (`HttpRequest`, `HttpResponse`, typed URL params).
- Use `get_object_or_404` for ID-based lookups.
- Enforce permissions early; return `403` when unauthorized.
- Filter querysets for the current user when applicable.
- Validate and sanitize request inputs (`GET`/`POST`).
- Render component HTML fragments with consistent template naming under `components/...`.
- Return appropriate statuses (`200`, `400`, `403`, `404`) and HTMX headers/events when useful.
- Extract complex logic into helper functions to keep views readable.

## HTMX integration rules
- Build endpoints that return partial HTML suitable for `hx-swap` updates.
- Support common patterns:
  - load-on-render (`hx-trigger="load"`)
  - delayed search input updates
  - form GET/POST flows with success + validation re-rendering.
- Use `HX-Trigger` response headers for cross-component refresh/close events after successful actions.

## References
- Load `references/bloomerp_components_guide.md` for concrete examples and detailed conventions copied from project instructions.
