# Dropdown Components

These templates provide a reusable dropdown system for Bloomerp:

- `body.html`: top-level dropdown container and trigger
- `item.html`: clickable dropdown item
- `submenu.html`: nested side-opening submenu
- `divider.html`: visual separator
- `title.html`: small section label

## Basic dropdown

```django
<c-ui.dropdown.body trigger_text="Options" position="right" size="sm">
    <c-ui.dropdown.item text="Open" icon="fa-solid fa-folder-open" />
    <c-ui.dropdown.item text="Delete" icon="fa-solid fa-trash" danger=True />
</c-ui.dropdown.body>
```

## HTMX item

```django
<c-ui.dropdown.item
    text="Open details"
    icon="fa-solid fa-arrow-right"
    hx_get="{% url 'some_component_url' %}"
    hx_target="#main-content"
    hx_swap="innerHTML"
    close_menu=True
/>
```

Use `close_menu=True` when selecting the item should dismiss the full dropdown tree.

## Custom item content

`c-ui.dropdown.item` also accepts slotted content directly. When slot content is present, it is rendered inside a non-interactive container that uses the same spacing, colors, and hover styling as a regular dropdown item, without generating a wrapping `button` or `a` element.

```django
<c-ui.dropdown.item>
    <button type="button" class="flex w-full items-center justify-between gap-4 px-4 py-2 text-sm text-left text-gray-700 hover:bg-gray-100 hover:text-primary-800">
        <span>Revenue</span>
        <span class="text-xs text-muted">Number</span>
    </button>
</c-ui.dropdown.item>
```

Use the existing `text="..."` API when you want the built-in dropdown item button or link. Use slot content when you need full control over the inner markup, including rendering your own buttons or links, while keeping the standard dropdown item look and feel.

## Nested submenu

```django
<c-ui.dropdown.submenu text="More actions" icon="fa-solid fa-bars">
    <c-ui.dropdown.item text="Archive" icon="fa-solid fa-box-archive" />
    <c-ui.dropdown.item text="Duplicate" icon="fa-solid fa-copy" />
</c-ui.dropdown.submenu>
```

### Submenu options

- `text`: label shown in the parent menu
- `icon`: optional leading icon
- `width`: nested menu width class, for example `w-64`
- `menu_class`: extra classes for the submenu panel
- `class`: extra classes for the submenu trigger row
- `disabled`: disables the submenu trigger
- `direction`: `auto`, `right`, or `left`
- `event_name`: custom Alpine event name if multiple submenu groups need separate coordination

`direction="auto"` is the default and is recommended. It opens right when there is enough viewport space and falls back left when needed.

## Top-level dropdown options

Supported `c-ui.dropdown.body` parameters:

- `trigger_text`
- `trigger_icon`
- `trigger_icon_class`
- `trigger_button_class`
- `trigger_class`
- `menu_class`
- `position`: `left`, `right`, or `center`
- `direction`: `up` or `down`
- `size`: `sm`, `md`, or `lg`
- `width`
- `disabled`
- `icon`
- `wrapper_class`
- `trigger_selector`
- `trigger_html`
- `close_on_item_event`

## Design notes

- Prefer `c-ui.dropdown.submenu` over hand-rolled nested Alpine blocks.
- Prefer `close_menu=True` for submenu leaf actions so the whole menu closes after selection.
- Keep submenu content flat and action-oriented. If a submenu starts holding forms or large previews, it should probably become a modal instead.
