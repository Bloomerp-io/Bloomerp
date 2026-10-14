# `c-ui.chat.container`

Shared scrollable message log for comments and instant messaging. Use inside an
`im-theme` ancestor to apply the shared chat styling.

| Parameter | Description |
| --- | --- |
| `class` | Additional classes for the log. |
| `label` | Accessible log label; defaults to translated “Messages”. |

The default slot holds messages. Additional attributes, including activity
tracking attributes, are forwarded to the log.
