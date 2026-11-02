# `c-ui.inputs.sql_query_editor`

Render the SQL catalog, editor, execution controls, and paginated results.
`name` defaults to `query`; `value` initializes the hidden query field. The
default slot supplies the editor textarea. Render with a request context so
the component has a CSRF token. SQL access remains subject to server permissions.

Source: `bloomerp/django_bloomerp/bloomerp/templates/cotton/ui/inputs/sql_query_editor.html`.
