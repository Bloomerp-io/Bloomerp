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
