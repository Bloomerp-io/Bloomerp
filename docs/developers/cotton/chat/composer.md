# `c-ui.chat.composer`

Shared rich-text editor, send button, and Ctrl/⌘+Enter shortcut for comments and
instant messaging. Place it inside a caller-owned form and an `im-theme`
ancestor. Ordinary Enter inserts a newline.

| Parameter | Description |
| --- | --- |
| `name` | Editor field name; defaults to `body_html`. |
| `label` | Accessible editor label; defaults to translated “Message”. |
| `placeholder` | Editor placeholder. |
| `disabled` | String `true` disables sending. |
| `include_toolbar` | Whether to show the rich-text toolbar. |
| `class` | Additional composer classes. |

The default slot holds content above the editor. The component submits its
owning form through `requestSubmit` and leaves submission, pending state,
errors, and successful draft clearing to the caller. Comments use HTMX; instant
messaging uses `Conversation` and its existing acknowledgement flow.
