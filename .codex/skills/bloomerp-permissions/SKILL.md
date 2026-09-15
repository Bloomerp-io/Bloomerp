---
name: bloomerp-permissions
description: "Inspect or change Bloomerp authorization across Django permissions, Policy assignments, row and field rules, unified AccessRule compilation, APIs, components, views, SQL, and object visibility. Use whenever behavior depends on who may view, create, change, delete, import, export, or bulk-operate on models, rows, or fields."
---

# Bloomerp Permissions

Bloomerp authorization is layered. Trace the complete request path before changing behavior; an entrypoint gate, row filter, field filter, and API access rule may all participate.

## Workflow

1. Identify the requested capability and enforcement surfaces: global/model, row, field, object, API, component/view, SQL, or bulk operation.
2. Read `references/permission_system.md` before changing behavior or debugging an unexpected access result.
3. Prefer the existing `UserPolicyManager`, `PolicyManager`, `ApiAccessResolver`, and permission compilers over duplicating access logic.
4. Preserve and test superuser, anonymous, direct-user policy, group-policy, and normal-user-with-no-policy behavior as relevant.
5. Add focused tests under `bloomerp/django_bloomerp/bloomerp/tests/permissions/`, plus API, component, view, SQL, or end-to-end coverage at the enforcement boundary being changed.

## Essential Rules

- `BloomerpModel.Meta.default_permissions` comes from `BloomerpPermission`: `add`, `change`, `delete`, `view`, `export`, `import`, `bulk_add`, `bulk_change`, and `bulk_delete`.
- Use `UserPolicyManager` for a user's compiled global, row, field, and object access. `get_queryset(...)` remains a compatibility alias for `get_accessible_queryset(...)`.
- `create_permission_str(model, action)` returns a bare model codename such as `view_customer`. Direct Django `user.has_perm(...)` calls require a qualified string such as `sales.view_customer`; manager APIs normalize bare, qualified, and enum inputs.
- `Policy.global_permissions` is enforced by `UserPolicyManager.has_global_permission(...)` alongside Django user/group permissions.
- Stored row permissions are content-type-scoped `auth.Permission` objects. Their rule JSON is a shared `Filter` tree; new code should use `FilterCondition(field_path=..., lookup_id=..., value=...)` rather than the legacy `RowPolicyRuleCondition` adapter.
- `FieldPolicy.rule` is keyed by `ApplicationField` ID and stores bare model codenames. `__all__` grants the matching permission across all fields for that content type.
- Treat row and field access as allow-lists. Multiple applicable access rules union access; conditions inside one row rule follow that rule's `AND` or `OR` connector.
- `AbstractBloomerpUser.get_content_types_for_user(...)` reflects Django user/group permissions only, not policy-derived row or field access.
- If model-configured API access is involved, also use `$bloomerp-model-config`.

## Reference

Read `references/permission_system.md` for current schemas, compilers, API action mapping, source locations, and test routing.
