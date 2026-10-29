# `c-ui.inputs.permissions`

Render permission checkboxes. Supply `id`, the submitted field `name`, a
`permissions` iterable with `codename` and `name`, and `selected_permissions`
containing the selected codenames. With multiple permissions, an all-permissions
checkbox submits `__all__`. Validate and authorize submitted grants on the server.

Source: `bloomerp/django_bloomerp/bloomerp/templates/cotton/ui/inputs/permissions.html`.
