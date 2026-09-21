# `c-ui.modal`

- Tag: `<c-ui.modal />`
- Source: `bloomerp/django_bloomerp/bloomerp/templates/cotton/ui/modal.html`
- TypeScript component id: `modal`

## Description

Cotton declares the modal's options and body/footer slots. The modal shell
(backdrop, header, controls, body and footer) is built in
`static_src/ts/utils/modals.ts`; `Modal.ts` owns instance behavior.

Existing `bloomerp-open-modal`, `bloomerp-close-modal`, fullscreen and title
attributes continue to address declared modals by ID. The modal manager tracks
opening order, traps focus in the top dialog, and keeps page scrolling locked
until the last dialog closes.

For nested asynchronous flows, use `createModalInstance(declarationId, opener)`
to create an empty, disposable dialog with the declaration's visual options.
Pass its `getBodyElement()` as both the HTMX request `source` and `target`.
Forms returned into it should use `hx-target="closest [data-modal-body]"` so
validation responses stay with the submitting instance. Close the captured
instance when the operation finishes. Its content and listeners are disposed
after closing; parent dialogs retain their live DOM and entered values.

Foreign-field creation and advanced selection use this instance API. Legacy
general-purpose callers still reuse their explicitly named modal; they can be
migrated individually. Dragging, resizing, tabs, and page navigation/refresh
handling are not part of this change.

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
