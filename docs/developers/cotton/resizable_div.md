# `c-ui.resizable_div`

- Tag: `<c-ui.resizable_div />`
- Source: `bloomerp/django_bloomerp/bloomerp/templates/cotton/ui/resizable_div.html`
- TypeScript component id: `resizable-div`

## Description

A resizable div will have a resize handler and store the value to the cookies so that will
maintain the same value on a page refresh.

## Parameters

| Name | Type | Description |
| --- | --- | --- |
| `id` | str | The id of the resizable div. This will be used to store the value in the cookies. |
| `start_width` | str | The initial width of the resizable div. Is a string with the unit, e.g. "200px" or "50%". |
| `fit_to_main_bottom` | bool, optional | If true, keep the div height aligned with the bottom of the main panel. |
| `class` | str, optional | Additional classes to add to the resizable div. Default is "". |

## Slots

| Name | Type | Description |
| --- | --- | --- |
| `default` | - | - |
