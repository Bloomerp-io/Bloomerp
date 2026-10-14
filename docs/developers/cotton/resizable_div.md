# `c-ui.resizable_div`

- Tag: `<c-ui.resizable_div />`
- Source: `bloomerp/django_bloomerp/bloomerp/templates/cotton/ui/resizable_div.html`
- TypeScript component id: `resizable-div`

## Description

A panel with a configurable resize handle, sizing limits, and persisted width.
Existing instances use cookies and desktop-only resizing by default. Split view
opts into local storage and resizing at all viewport widths.

## Parameters

| Name | Type | Description |
| --- | --- | --- |
| `id` | str | The id of the resizable div. This will be used to store the value in the cookies. |
| `start_width` | str | The initial width of the resizable div. Is a string with the unit, e.g. "200px" or "50%". |
| `fit_to_main_bottom` | bool, optional | If true, keep the div height aligned with the bottom of the main panel. |
| `resize_from` | str, optional | Edge used as the resize handle: `left` (default) or `right`. |
| `class` | str, optional | Additional classes to add to the resizable div. Default is "". |
| `style` | str, optional | Instance-specific inline styling. Width is managed by the component. |
| `handle_class` | str, optional | Replace the default handle classes, including positioning and appearance. |
| `handle_line_class` | str, optional | Replace the default handle-line classes. |
| `min_width` | number, optional | Minimum width in pixels; defaults to `0`. Positive values prevent collapse. |
| `min_remaining_width` | number, optional | Reserve space for the neighboring pane in pixels; defaults to `0`. |
| `max_width_ratio` | number, optional | Maximum fraction of the resize container; defaults to `0.75`. |
| `responsive` | bool, optional | Set `false` to keep resizing enabled below the desktop breakpoint. |
| `storage` | str, optional | `cookie` (default) or `local`. Local storage stores numeric pixel widths. |
| `storage_key` | str, optional | Explicit persistence key; allows reusing an existing saved width. |

Place the panel inside an element with `data-resizable-div-container` to define
its width limits. Extra HTML attributes are forwarded to the panel root. The
split-view call site supplies its existing local-storage key, a right-edge
handle with custom classes, and minimum widths for both panes.

## Slots

| Name | Type | Description |
| --- | --- | --- |
| `default` | - | - |
