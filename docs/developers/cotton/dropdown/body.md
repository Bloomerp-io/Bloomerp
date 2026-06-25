# `c-ui.dropdown.body`

- Tag: `<c-ui.dropdown.body />`
- Source: `bloomerp/django_bloomerp/bloomerp/templates/cotton/ui/dropdown/body.html`

## Description

Bloomerp dropdown component.

## Parameters

| Name | Type | Description |
| --- | --- | --- |
| `slot` | - | everything inside of the component |
| `trigger_text` | - | text to display on the dropdown button (default: "Options") |
| `trigger_icon` | - | HTML for a custom icon to display instead of text (default: None) |
| `trigger_icon_class` | - | CSS classes for a Font Awesome or other icon element rendered before the trigger text |
| `trigger_button_class` | - | use btn-based trigger styling instead of the default inline trigger styling |
| `trigger_class` | - | additional CSS classes for the trigger button |
| `menu_class` | - | additional CSS classes for the dropdown menu |
| `position` | - | dropdown position - "left", "right", or "center" (default: "right") |
| `direction` | - | dropdown direction - "up" or "down" (default: "down") |
| `size` | - | dropdown size - "sm", "md", "lg" (default: "md") |
| `width` | - | custom width class for the dropdown menu (e.g. "w-80"). Overrides size. |
| `disabled` | - | whether the dropdown is disabled (default: False) |
| `icon` | - | whether to show the arrow indicator icon (default: True; ignored when trigger_icon is set) |
| `close_on_item_event` | - | event name used to close this dropdown from nested items/submenus (default: "dropdown-close") |
| `fixed` | - | whether the dropdown menu should be positioned relative to the viewport to avoid clipped overflow containers |
