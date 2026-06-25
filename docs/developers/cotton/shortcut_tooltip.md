# `c-ui.shortcut_tooltip`

- Tag: `<c-ui.shortcut_tooltip />`
- Source: `bloomerp/django_bloomerp/bloomerp/templates/cotton/ui/shortcut_tooltip.html`
- TypeScript component id: `shortcut-tooltip`

## Description

Component that allows you to create shortcuts which has tooltips

## Parameters

| Name | Type | Description |
| --- | --- | --- |
| `shortcut` | string | the actual shortcut (ex. mod+k) |
| `action` | string | focus | click | ... (more tbd) |
| `position` | string | bottom | top | right | left |
| `text` | string | optional text |
| `target` | string | optional query selector for the element that should receive the initial action |
| `focus_target` | string | optional query selector for the element that should be focused after the action runs |
| `focus_scope` | string | where to search for `focus_target` |

Additional details:

  - `self` (default): search inside the shortcut tooltip wrapper
  - `target`: search inside the action target matched by `target`
  - `document`: search anywhere in the document
  - any other value: treated as a custom query selector for the scope container

## Examples

- Open a dropdown and focus its first input inside the wrapper:
  `focus_target="#filter-section input"`
- Open something elsewhere and focus globally:
  `focus_target="[data-command-palette-input]" focus_scope="document"`

## Slots

| Name | Type | Description |
| --- | --- | --- |
| `default` | - | - |
