# CRUD Layout View Abstraction

The create view and detail overview now share a single CRUD layout abstraction in [`form.py`](./form.py).

## What Is Shared

- Layout preference loading and repair.
- Content-type resolution for CRUD layouts.
- Resolution of layout rows into a single item context shape.
- Shared field rendering through `build_crud_layout_field_context(...)`.
- Shared container wiring for:
  - field rendering
  - available fields
  - layout persistence

## Shared Item Context

Every rendered CRUD layout item now uses the same context contract:

- `application_field`
- `value`
- `input`
- `help_text`
- `errors`
- `is_required`
- `colspan`
- `can_edit`

Create and detail no longer diverge at the template level. The difference is only the bound source:

- Create: a bound Django form field.
- Detail: either a bound change form field or a readonly object value.

## What Still Stays View-Specific

Create-specific behavior in [`../core/create_view.py`](../core/create_view.py):

- add permission checks
- addable-field filtering
- required-field blocking
- create row-policy validation
- injected-field rejection

Detail-specific behavior in [`../detail/overview.py`](../detail/overview.py):

- object lookup and view access
- editable-field filtering from change permissions
- update row-policy validation
- injected-field rejection for updates
- detail tab behavior from the base detail view

## Endpoint Contract

The live CRUD layout flow no longer depends on `layout_kind` for field rendering.

- Field rendering:
  - `crud_layout_render_field` infers create vs detail from `object_id`
- Layout persistence:
  - create and detail have separate endpoints
- Available fields:
  - create and detail have separate endpoints

Legacy `layout_kind` handling remains only in the old shared preference/available-field endpoints for compatibility.
