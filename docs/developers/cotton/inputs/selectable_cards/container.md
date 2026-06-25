# `c-ui.inputs.selectable_cards.container`

- Tag: `<c-ui.inputs.selectable_cards.container />`
- Source: `bloomerp/django_bloomerp/bloomerp/templates/cotton/ui/inputs/selectable_cards/container.html`
- TypeScript component id: `selectable-cards`

## Description

A container for searchable cards. Each card can

## Parameters

| Name | Type | Description |
| --- | --- | --- |
| `include_search` | bool | whether it is searchable |
| `value` | any | the selected value |
| `values` | any | list of values (in case multiple selectable are possible) |
| `allow_multiple` | bool | whether it's possible to allow for multiple selected cards |
| `name` | str | the input name |
| `items` | list[dict] | optionally will create the items inside of the slot section. Dict has parameters for items |
