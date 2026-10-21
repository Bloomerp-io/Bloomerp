# Model configuration

Inherit from `BloomerpModel`, put each model in its own file, and import it from
your app's `models/__init__.py`. The [getting-started example](../getting-started.md)
shows a model and its owning module.

Attach a `BloomerpModelConfig` instance as `bloomerp_config`. Import configuration
types from `bloomerp.models.definition`.

| Setting | Use |
| --- | --- |
| `module` | Owning module ID or `BloomerpModule` class; use the singular name. |
| `icon`, `description` | Model presentation metadata. |
| `detail_view_settings` | Named field layouts, detail tabs, and skipped detail routes. |
| `model_view_settings` | Default dataviews, toolbar actions, and skipped collection routes. |
| `tiles` | Reusable [workspace tile configurations](../workspaces/index.md). |
| `permission_settings` | Named default stored policies synchronized by `sync_defaults`. |
| `string_search_settings` | Search field paths and global-search participation. |
| `activity_log_settings` | Whether model activity is recorded. |
| `object_actions` | Object-specific buttons, HTML, or modals. |
| `create_redirect_url_func` | Callback selecting the redirect after creation. |
| `api_settings` | Generated API enablement, additional access grants, and nesting. |

A module is discovered from an installed app's `modules.py` or `modules/`
package. Use stable module IDs. The router needs a registered module for a
model's collection and detail pages; inspect module membership when those pages
are missing.

## Layouts and collection views

Put field layouts under `DetailViewSettings(layouts=[...])` and collection
preferences under `ModelViewSettings(default_dataviews=[...])`. Each nonempty
list must have unique names and exactly one entry with `is_default=True`.
`skip_views` contains the route's `url_name`, not its display label or path.

See [dataview configuration](../dataviews/index.md#model-defaults),
[toolbar actions](../dataviews/actions.md#configured-toolbar-actions-are-different),
and [router names](../router/index.md#names-and-url-names).

## Generated APIs and access

If `api_settings` is omitted, API generation follows
`BLOOMERP_CONFIG.auto_generate_api_endpoints`. If supplied,
`ApiSettings.enable_auto_generation` controls generation; its default is false.
Enabling an endpoint does not grant access to its data.

Use `ApiAccessSettings` for grants in addition to stored user policies. For
example, this configuration exposes active products' IDs and names for reading:

```python
from bloomerp.filters.definition import FilterCondition
from bloomerp.models.definition import ApiAccessSettings, ApiSettings, BloomerpModelConfig
from bloomerp.permissions.definition import AccessRule, BloomerpPermission, RowPolicyRuleContent


product_config = BloomerpModelConfig(
    api_settings=ApiSettings(
        enable_auto_generation=True,
        access=ApiAccessSettings(
            anonymous=[
                AccessRule(
                    row_permissions=[
                        RowPolicyRuleContent(
                            permissions=[BloomerpPermission.VIEW],
                            conditions=[
                                FilterCondition(
                                    field_path="active",
                                    lookup_id="equals",
                                    value=True,
                                ),
                            ],
                        ),
                    ],
                    field_permissions={
                        "id": [BloomerpPermission.VIEW],
                        "name": [BloomerpPermission.VIEW],
                    },
                ),
            ],
        ),
    ),
)
```

Assign this to a model with `active` and `name` fields. Rules must grant both row
and field access. They use permission names (`view`, `add`, `change`, `delete`,
`bulk_add`), not REST action names (`list`, `retrieve`, `create`). Empty AND row
conditions grant all rows; empty OR conditions grant none.

`anonymous` applies without authentication. `authenticated` adds grants for
signed-in callers. By default, authenticated callers also inherit anonymous
grants; set `inherit_anonymous_for_authenticated=False` when that is unwanted.
These are additive grants, so a restrictive rule does not revoke another rule's
access. Use the [shared filter format](../fields/execution.md) for predicates.

## Response nesting

`ApiSettings.nesting` contains `ApiNesting` entries:

```python
from bloomerp.models.definition import ApiNesting


customer_nesting = ApiNesting(
    for_field="customer",
    fields=["id", "name"],
    on_action=["read"],
    auto_pk=True,
)
```

`on_action` accepts `list` and `read`. Nesting controls response shape; it grants
no row or field access. The parent relation and related data must both be
readable. Use explicit field lists and explicit deeper paths such as
`customer.address`; nesting is not implicitly recursive.

## Verify a model

Run migrations and `save_application_fields` after field changes, then generate
and extend the model's [test case](../testing/model-test-case.md). API grants
also need [request scenarios](../testing/view-test-case.md) covering the intended
anonymous and authenticated callers.
