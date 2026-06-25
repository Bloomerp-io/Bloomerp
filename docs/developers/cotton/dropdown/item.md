# `c-ui.dropdown.item`

- Tag: `<c-ui.dropdown.item />`
- Source: `bloomerp/django_bloomerp/bloomerp/templates/cotton/ui/dropdown/item.html`

## Description

Bloomerp dropdown item component.

## Parameters

| Name | Type | Description |
| --- | --- | --- |
| `href` | - | URL for the link (optional) |
| `hx_get` | - | HTMX get URL (optional) |
| `hx_post` | - | HTMX post URL (optional) |
| `hx_target` | - | HTMX target selector (optional) |
| `hx_swap` | - | HTMX swap method (optional) |
| `hx_push_url` | - | whether to push URL to history (optional) |
| `hx_vals` | - | HTMX values JSON payload (optional) |
| `onclick` | - | JavaScript onclick handler (optional) |
| `icon` | - | icon class (optional) |
| `text` | - | text content fallback when no slot content is provided |
| `slot` | - | optional custom item content rendered inside the item |
| `class` | - | additional CSS classes |
| `type` | - | "link", "button", "divider" (default: "link") |
| `danger` | - | whether this is a destructive action (default: False) |
| `disabled` | - | whether the item is disabled (default: False) |
| `close_menu` | - | whether clicking the item should close parent dropdown menus (default: False) |
