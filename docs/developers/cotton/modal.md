# `c-ui.modal`

- Tag: `<c-ui.modal />`
- Source: `bloomerp/django_bloomerp/bloomerp/templates/cotton/ui/modal.html`
- TypeScript component id: `modal`

## Description

Modal component.

## Parameters

| Name | Type | Description |
| --- | --- | --- |
| `id` | - | unique identifier for the modal (required) |
| `title` | - | modal title (optional) |
| `size` | - | modal size - "sm", "md", "lg", "xl", "full" (default: "md") |
| `closable` | - | whether the modal can be closed (default: True) |
| `backdrop_click_close` | - | close modal when clicking backdrop (default: True) |
| `show_header` | - | whether to show the header (default: True) |
| `show_footer` | - | whether to show the footer (default: False) |
| `header_class` | - | additional CSS classes for header |
| `body_class` | - | additional CSS classes for body |
| `body_padding` | - | padding classes for the modal body (default: "p-3") |
| `footer_class` | - | additional CSS classes for footer |
| `slot` | - | main content of the modal |
| `footer_slot` | - | footer content (buttons, etc.) |
