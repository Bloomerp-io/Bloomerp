# `c-ui.chat.message`

Shared bubble for object comments and instant messaging. Use inside an
`im-theme` ancestor to apply the shared chat styling.

## Parameters

| Name | Description |
| --- | --- |
| `sender` | Sender display name. |
| `message` | Sanitized rich HTML when the default slot is omitted. |
| `datetime` | Datetime displayed as `M j, H:i`. |
| `side` | `left` (default) or `right` for the current user's message. |
| `id` | Optional article ID. |
| `highlight` | String `true` highlights the bubble. |
| `class` | Additional article classes. |
| `background`, `variant` | Compatibility aliases; `primary` colors the bubble. |

## Slots

The default slot holds rich message content. `actions` holds caller-specific
controls beside the timestamp, and `reactions` holds content below the bubble.
Extra attributes are forwarded to the article. Comments supply neither threads
nor reactions; instant messaging retains these through its wrapper component.
