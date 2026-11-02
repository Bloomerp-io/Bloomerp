# `c-ui.inputs.text_editor`

Render a rich-text editor backed by a hidden form input. Supply `name` and
initial HTML through `value`. Optional controls include `placeholder`, `disabled`,
`height`, `has_border`, and `include_toolbar`.

The Template command inserts an editable copy at the cursor. The cancellable
`bloomerp:template-selected` event exposes `detail.template` and `detail.insert`;
a specialized editor can prepare its context before inserting the template.
Object references and uploads use the configured component endpoints.

Source: `bloomerp/django_bloomerp/bloomerp/templates/cotton/ui/inputs/text_editor.html`.
