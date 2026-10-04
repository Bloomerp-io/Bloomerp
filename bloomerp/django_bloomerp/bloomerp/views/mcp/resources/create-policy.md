# Create permissions and policies

Bloomerp combines global model permissions, row allow-lists and field allow-lists.
A global grant alone does not provide all rows or fields. Applicable policy grants
union access; an ungranted row or field remains inaccessible to a normal user.
Superusers bypass permission checks. Anonymous access, where configured for APIs,
comes from model-configured anonymous AccessRule grants, not assigned user policies.

## Permission identity

Django auth.Permission stores `content_type`, `codename` and `name`. Bloomerp
models generate their default model permissions during migrations. Reuse those
records. For a custom capability, create a Permission scoped to the intended
ContentType with a unique codename and descriptive name through authorized Django
administration/code; enforcement code must actually check that capability.
Inventing a codename does not automatically create a new supported API action.

For a model named customer, `view_customer` is a bare codename.
`create_permission_str(Customer, "view")` returns that bare form. Direct Django
checks use `sales.view_customer`; UserPolicyManager normalizes enum, bare and
qualified forms for the target model. Always resolve Permission records by both
codename and ContentType, and verify their scope before attaching grants.

## Create through the policy API

The registered PolicyListApiView and PolicyDetailApiView expose create/list and
retrieve/update/delete through the model/detail API router. Resolve their URLs
from the instance's API schema/router rather than inventing a path. These views
require an authenticated staff user (IsAdminUser). PolicySerializer accepts this
nested shape; replace example model codenames, ContentType and ApplicationField
IDs with authorized metadata from your instance:

```json
{
  "name": "Customer readers",
  "description": "View permitted customer records",
  "content_type_id": 42,
  "global_permissions": ["view_customer"],
  "row_policy": {
    "name": "All customer rows",
    "rules": [{"rule": {"connector": "AND", "conditions": []}, "permissions": ["view_customer"]}]
  },
  "field_policy": {"name": "Customer fields", "rules": {"__all__": ["view_customer"]}}
}
```

`field_policy.rules` is the API name; the stored FieldPolicy attribute is `rule`.
Row permissions are a separate array beside `rule`, stored as auth.Permission
relations; putting permissions only inside the rule JSON does not assign grants.
API row and field codenames must also be selected in `global_permissions`.
All permission records must belong to the target ContentType. The current API's
PermissionCodenameField resolves by codename alone, so avoid ambiguous codenames
across applications and use scoped server-side creation when ambiguity exists.
The serializer creates RowPolicy, its rules, FieldPolicy and Policy atomically.
Updates cannot change the target ContentType and replace row rules and global
permissions; include the complete intended nested configuration.

## Row and field configuration

For filtered rows use the shared Filter schema, for example:
`{"connector": "AND", "conditions": [{"field_path": "country__name", "lookup_id": "equals", "value": "Belgium"}]}`.
Use actual model field paths and registered terminal lookup IDs. Conditions in a
rule follow AND or OR; separate matching rules union their rows. Empty AND matches
all rows; empty OR matches none. Runtime user binding supports `$user` and the
`equals_user` lookup where applicable. Property and unsupported one-to-many fields
cannot be used for row predicates. Legacy application_field_id/operator condition
objects are migration compatibility input; use field_path/lookup_id for new rules.

Stored FieldPolicy.rule maps string ApplicationField IDs to bare model codenames,
for example `{"123": ["view_customer", "change_customer"]}`. `__all__` grants
the listed actions across fields for the policy's ContentType; use it only when
all those fields should be available. RowPolicy and FieldPolicy must target the
same intended ContentType. Stored policies compile to the unified AccessRule
representation used by the existing Django, Python and SQL permission compilers.

## Assign and verify

PolicySerializer does not accept users or groups. After creating the policy,
assign subjects through authorized policy editing UI or server-side Policy methods:
`assign_user(user)`, `assign_users(users)`, `assign_group(group)` or
`assign_groups(groups)`. Remove assignments through the corresponding `users` or
`groups` many-to-many relation. Group members inherit that group's assigned
policies in addition to their direct assignments. Changes require authority to
manage that policy; reading this reference grants no mutation permissions.

UserPolicyManager.has_global_permission combines Django direct/group grants and
assigned Policy.global_permissions. Verify get_accessible_queryset for rows,
get_accessible_fields for fields, get_accessible_fields_for_object for row-sensitive
fields, and has_access_to_object for persisted objects. A normal user with no
applicable row or field grants receives no rows or fields. Use
get_accessible_content_types for policy-aware discovery.

Generated model APIs use ApiAccessResolver to merge stored policies with
model-configured authenticated and, when inherited, anonymous AccessRule grants.
Read/list/retrieve maps to view, create to add, update/partial_update to change,
destroy to delete, and bulk_create to bulk_add. AccessRule row_permissions uses
the same Filter rules; field_permissions there can use model field names.
Check the actual API contract before using generic MCP object mutation tools:
the dedicated policy serializer and separate assignment methods are authoritative.
Test grants with an ordinary intended user, including row visibility, returned
fields, writable fields and unsaved create/update candidates.
