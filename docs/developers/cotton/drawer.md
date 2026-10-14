# `c-ui.drawer`

Reusable drawer controlled by `bloomerp-open-drawer` and
`bloomerp-close-drawer` attributes. Escape and backdrop clicks close it.

| Parameter | Description |
| --- | --- |
| `id` | Required unique drawer ID. |
| `side` | `left` or `right` (default). |
| `size` | `sm`, `md` (default), `lg`, `xl`, or `full`. |
| `backdrop` | Show a modal backdrop; defaults to True. |
| `backdrop_click_close` | Close when the backdrop is clicked; defaults to True. |
| `lock_scroll` | Lock page scrolling while open; defaults to True. |
| `portal_to_body` | Move outside ancestor stacking contexts while open. |
| `class`, `style` | Custom overlay classes and inline styles. |
| `panel_class`, `panel_style` | Custom panel classes and inline styles. |

The default slot contains the panel content. Extra attributes are forwarded to
the overlay. For a nonmodal drawer, set `:backdrop="False"`,
`:lock_scroll="False"`, `class="pointer-events-none"`, and
`panel_class="pointer-events-auto"` so the surrounding page remains usable.

List views reuse this component for Drawer view mode. Rendering context may
supply `detail_drawer_class`, `detail_drawer_panel_class`, and
`detail_drawer_panel_style` to customize the detail drawer.
