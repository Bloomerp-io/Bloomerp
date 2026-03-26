# BloomERP Permission System

Use this file when changing permission behavior or debugging why a user can or cannot see, edit, or query something.

## Core Files
- `bloomerp/django_bloomerp/bloomerp/models/base_bloomerp_model.py`
- `bloomerp/django_bloomerp/bloomerp/models/users/user.py`
- `bloomerp/django_bloomerp/bloomerp/models/access_control/policy.py`
- `bloomerp/django_bloomerp/bloomerp/models/access_control/field_policy.py`
- `bloomerp/django_bloomerp/bloomerp/models/access_control/row_policy.py`
- `bloomerp/django_bloomerp/bloomerp/models/access_control/row_policy_rule.py`
- `bloomerp/django_bloomerp/bloomerp/services/permission_services.py`
- `bloomerp/django_bloomerp/bloomerp/views/api_views.py`
- `bloomerp/django_bloomerp/bloomerp/tests/access_control/test_permission_services.py`

## Mental Model
BloomERP permissions are not a single mechanism.

1. Django auth permissions gate coarse capabilities.
2. `Policy` assigns access-control bundles to users and groups.
3. `RowPolicy` plus `RowPolicyRule` decide which records a non-superuser can access.
4. `FieldPolicy.rule` decides which fields a non-superuser can read or write.
5. API and component code may still apply explicit `has_perm(...)` checks at the entrypoint.

Changes are usually only correct when the relevant layers stay aligned.

## Model-Level Permissions
`BloomerpModel.Meta.default_permissions` defines the generated codenames:
- `add`
- `change`
- `delete`
- `view`
- `bulk_change`
- `bulk_delete`
- `bulk_add`
- `export`

This means BloomERP expects codenames such as `view_customer`, `bulk_change_customer`, and `export_customer`.

For direct auth checks, the full string is typically:
- `f"{model._meta.app_label}.view_{model._meta.model_name}"`

## Policy Assignment
`Policy` is the aggregate access-control object.

- `users` and `groups` attach the policy to subjects.
- `row_policy` controls record-level access.
- `field_policy` controls field-level access.
- `global_permissions` exists, but enforcement is not wired through the main permission service.

`UserPermissionManager.get_user_policies()` resolves policies from both direct user assignment and group membership.

## Field Policies
`FieldPolicy.rule` is JSON keyed by `ApplicationField.id`.

Example shape:

```json
{
  "__all__": ["view_customer"],
  "123": ["view_customer", "change_customer"],
  "124": ["view_customer"]
}
```

Important details:
- Keys are field ids as strings or ints.
- Values are bare codenames such as `view_customer`, not `bloomerp.view_customer`.
- `__all__` is a wildcard grant for all fields on that content type.
- No matching field policy means `UserPermissionManager.has_field_permission(...)` returns `False` for non-superusers.

`get_accessible_fields(...)` unions matching grants across the user's field policies.

## Row Policies
`RowPolicy` is just a container for rules scoped to one content type.

`RowPolicyRule` contains:
- `row_policy`
- `rule` JSON
- `permissions` many-to-many to `auth.Permission`

Typical rule shape:

```json
{
  "application_field_id": "123",
  "operator": "equals",
  "value": "Belgium"
}
```

Important details:
- Rule permissions are stored as `Permission` objects for the same content type as the row policy.
- `add_permission("view_customer")` resolves the permission against the row policy content type.
- `UserPermissionManager.get_queryset(...)` keeps only rules whose attached permission codename matches the requested permission.
- Matching row rules combine with OR semantics.
- No row policies or no matching rules means an empty queryset for non-superusers.

Supported rule patterns visible in tests:
- direct field equality
- contains
- greater-than-or-equal
- user-relative lookups such as `"$user"`
- related-field operators like `__country__name`
- nested related-field operators like `__country__planet__name`

## API Enforcement
`BloomerpModelViewSet` is the main permission-aware API path.

- `get_queryset()` delegates row filtering to `UserPermissionManager.get_queryset(...)`.
- `_apply_field_permissions(...)` strips disallowed serializer fields from read responses.
- `_enforce_write_field_permissions(...)` rejects writes to fields without the requested field permission.
- Action-to-permission mapping is:
  - `list`, `retrieve` -> `view`
  - `create` -> `add`
  - `update`, `partial_update` -> `change`
  - `destroy` -> `delete`

If an API task changes permissions, verify both queryset behavior and serializer field behavior.

## Components And Layouts
Permission-sensitive UI code appears in two patterns:

- Direct `request.user.has_perm(...)` gates for top-level capability checks.
- `UserPermissionManager` gates for row/field-sensitive rendering.

Examples worth checking:
- `bloomerp/django_bloomerp/bloomerp/components/detail_layout_render_field.py`
- `bloomerp/django_bloomerp/bloomerp/services/sectioned_layout_services.py`
- `bloomerp/django_bloomerp/bloomerp/components/datatable.py`
- `bloomerp/django_bloomerp/bloomerp/components/objects/dataview.py`

## Important Limitations And Sharp Edges
- `UserPermissionManager.has_global_permission(...)` is currently a stub.
- `AbstractBloomerpUser.get_content_types_for_user(...)` only reflects Django user/group permissions, not policy-derived row or field access.
- Some code paths still rely only on `has_perm(...)`, so adding a policy may not be enough if the entrypoint has its own auth gate.
- `PolicySerializer.PermissionCodenameField.to_internal_value(...)` fetches `Permission` by codename alone, so inspect carefully if a serializer change could confuse content types.
- `RowPolicyRule.is_valid_rule()` is currently recursive and should not be treated as a reliable validation helper; the effective validation path is `validate_rule()` via `clean()` / `save()`.

## Tests To Extend First
Start with:
- `bloomerp/django_bloomerp/bloomerp/tests/access_control/test_permission_services.py`

That file already covers:
- superuser access
- no-policy behavior
- field policy grants
- row policy grants
- related-field operators
- API list filtering
- API write denial on disallowed fields
