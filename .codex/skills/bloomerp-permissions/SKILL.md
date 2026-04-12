---
name: bloomerp-permissions
description: "Inspect and modify BloomERP's permission system, including Django `has_perm(...)` checks, model permission codenames, `Policy.global_permissions`, `FieldPolicy.rule`, `RowPolicy` and `RowPolicyRule`, `UserPermissionManager`, API queryset filtering, field-level visibility, and permission-sensitive components or views. Use when any task touches permissions, access control, authorization, record visibility, editability, queryset scoping, access-control serializers, or UI behavior gated by permissions."
---

# Bloomerp Permissions

Use this skill before changing permission-sensitive code. BloomERP authorization is layered, and a correct change usually needs alignment across Django model permissions, policy assignment, row filtering, field filtering, and UI/API enforcement.

## Quick Workflow
1. Identify which permission layer the task touches: model capability, row visibility, field visibility, or a combination.
2. Trace the request path from the entrypoint to the enforcement point instead of assuming `has_perm(...)` is the whole story.
3. Read `references/permission_system.md` before editing if the task changes behavior rather than only renaming code.
4. Preserve superuser behavior and the current default for normal users with no assigned policy.
5. Add or update permission tests when behavior changes.

## Permission Layers
- Use Django auth permissions for coarse action gates such as `request.user.has_perm(f"{app_label}.view_{model}")`.
- Use `BloomerpModel.Meta.default_permissions` as the canonical source for generated model-level codenames: `add`, `change`, `delete`, `view`, `bulk_change`, `bulk_delete`, `bulk_add`, `export`.
- Use `Policy` to attach access control to users and groups. A policy combines one `RowPolicy`, one `FieldPolicy`, and optional `global_permissions`.
- Use `UserPermissionManager.get_queryset(...)` for row-level access and `has_field_permission(...)` / `get_accessible_fields(...)` for field-level access.
- Use `BloomerpModelViewSet` for API enforcement. It filters rows through `get_queryset`, strips disallowed serializer fields on read, and rejects writes to denied fields.
- Use component/layout helpers that already call `UserPermissionManager` instead of duplicating permission logic.

## Working Rules
- Prefer `create_permission_str(model, action)` when building permission codenames in services or viewsets.
- Keep permission string formats straight:
  - Django `has_perm(...)` expects fully qualified strings like `bloomerp.view_customer`.
  - `FieldPolicy.rule` stores bare codenames like `view_customer`.
  - `RowPolicyRule.permissions` stores `auth.Permission` objects scoped to the content type.
- Treat field and row policies as allow-lists. No matching policy means no access for non-superusers.
- Remember that multiple row rules combine with OR semantics in `UserPermissionManager.get_queryset(...)`.
- Remember that field policies union together, and `__all__` grants a permission across all fields for that content type.
- Do not assume `Policy.global_permissions` is automatically enforced everywhere. Inspect call sites before depending on it.
- Do not assume `AbstractBloomerpUser.get_content_types_for_user(...)` reflects row or field policies. It derives from Django auth permissions only.

## Validation Checklist
- Check the direct permission gate at the entrypoint: view, component, serializer, command, or API endpoint.
- Check row access with `UserPermissionManager.get_queryset(...)` if records should be filtered.
- Check field visibility or editability with `has_field_permission(...)` / `get_accessible_fields(...)` if output or writes depend on specific fields.
- Check superuser behavior explicitly.
- Check the no-policy case explicitly for normal users.
- Update or add tests under `bloomerp/django_bloomerp/bloomerp/tests/access_control/` when changing permission behavior.

## References
- Load `references/permission_system.md` for the BloomERP-specific permission map, file locations, and current sharp edges.
