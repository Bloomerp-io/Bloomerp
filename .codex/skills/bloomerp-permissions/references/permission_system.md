# Bloomerp Permission System

Use this reference when changing permission behavior or tracing why a user can or cannot access a model, row, field, object, API response, component, or SQL query.

## Current Source Map

- Permission definitions and unified rules: `bloomerp/django_bloomerp/bloomerp/permissions/definition.py`
- Policy managers and helpers: `bloomerp/django_bloomerp/bloomerp/permissions/manager.py`
- Permission compilers: `bloomerp/django_bloomerp/bloomerp/permissions/compilers/`
- Stored policy models: `bloomerp/django_bloomerp/bloomerp/models/access_control/`
- Base model permissions: `bloomerp/django_bloomerp/bloomerp/models/base_bloomerp_model.py`
- API access resolution and nesting: `bloomerp/django_bloomerp/bloomerp/utils/api.py`
- DRF enforcement: `bloomerp/django_bloomerp/bloomerp/api/base.py`
- Access-control serializers: `bloomerp/django_bloomerp/bloomerp/serializers/access_control.py`
- Core manager tests: `bloomerp/django_bloomerp/bloomerp/tests/permissions/`

## Permission Vocabulary

`BloomerpPermission` defines these model permission prefixes:

- `add`, `change`, `delete`, `view`
- `export`, `import`
- `bulk_add`, `bulk_change`, `bulk_delete`

`BloomerpModel.Meta.default_permissions` uses the entire enum tuple.

Keep formats distinct:

- `create_permission_str(Customer, "view")` returns `view_customer`.
- `UserPolicyManager` and `PolicyManager` accept bare codenames, qualified codenames, and `BloomerpPermission` values and normalize them for the target model.
- A direct Django call uses `user.has_perm("app_label.view_customer")`.
- `FieldPolicy.rule` values are bare model codenames such as `view_customer`.
- `RowPolicyRule.permissions` and `Policy.global_permissions` store content-type-scoped `auth.Permission` objects.

## Stored Policies

`Policy` attaches to users and groups and combines one `RowPolicy`, one `FieldPolicy`, and optional `global_permissions`. `UserPolicyManager.get_user_policies()` resolves both direct assignments and group membership.

`has_global_permission(...)` grants a requested codename when either Django user/group permissions or an assigned policy's matching `global_permissions` contains it. Superusers bypass this check; anonymous users do not.

### Row policies

`RowPolicy` scopes its rules to one content type. Each `RowPolicyRule` stores:

- a `row_policy` foreign key;
- `rule` JSON validated as `RowPolicyRuleContent`;
- matching content-type `auth.Permission` objects through `permissions`.

The current rule schema is the shared filter schema. New code should construct `FilterCondition` values:

```python
from bloomerp.filters.definition import FilterCondition
from bloomerp.permissions.definition import RowPolicyRuleContent

rule = RowPolicyRuleContent(
    connector="AND",
    permissions=["view"],
    conditions=[
        FilterCondition(
            field_path="country__name",
            lookup_id="equals",
            value="Belgium",
        )
    ],
)
```

`RowPolicyRuleCondition(application_field_id=..., operator=..., value=...)` and its `field` alias remain migration inputs. Do not introduce them in new code.

An empty `AND` condition group matches all rows; an empty `OR` group matches none. Conditions inside one rule use its connector. Separate applicable row rules and policies union their matches.

`RowPolicyRule.save()` normalizes legacy input, validates the filter paths and terminal lookups, rejects unsupported property/one-to-many fields, and enforces permission content-type consistency. `is_valid_rule()` is a usable boolean wrapper around `validate_rule()`.

### Field policies

Stored `FieldPolicy.rule` JSON is keyed by `ApplicationField` ID:

```json
{
  "__all__": ["view_customer"],
  "123": ["view_customer", "change_customer"],
  "124": ["view_customer"]
}
```

`get_accessible_fields(...)` unions applicable grants. `get_accessible_fields_for_object(...)` applies row-sensitive field grants for one object. `annotate_field_permissions(...)` is the batch path when rendering per-row field visibility without an N+1 query pattern.

## Unified Access Rules and Compilers

`AccessRule` is the compiler-ready representation shared by stored policies and model-configured API access:

```python
AccessRule(
    row_permissions=[RowPolicyRuleContent(...)],
    field_permissions={"name": ["view", "change"]},
)
```

The compiler layer evaluates the same rule model in different contexts:

- `DjangoQPermissionCompiler`: querysets and row-sensitive field annotations;
- `PythonPermissionCompiler`: unsaved create/update candidates;
- `SqlPermissionCompiler`: SQL/table access paths.

Use these established paths instead of translating filter JSON independently.

## UserPolicyManager Entry Points

- `has_global_permission(...)`: Django plus policy global grants.
- `get_accessible_queryset(...)` / `get_queryset(...)`: stored-policy row filtering.
- `get_queryset_for_access_rules(...)`: evaluate supplied/draft access rules without loading stored policies.
- `get_accessible_fields(...)` and `has_field_permission(...)`: model-level field access.
- `get_accessible_fields_for_object(...)`: field access after row predicates are evaluated for one object.
- `has_access_to_object(...)`: global plus row access for a persisted object.
- `get_accessible_content_types(...)`: policy-aware content-type discovery.

Normal users with no applicable row rules receive an empty queryset. Normal users with no applicable field grants receive no fields. Check superusers and anonymous users explicitly rather than inferring their behavior from those defaults.

## Generated API Enforcement

`ApiAccessResolver` merges:

- stored user policies for authenticated users;
- model-configured authenticated rules;
- model-configured anonymous rules when anonymous inheritance is enabled.

Its action mapping is:

- `list`, `retrieve`, `read` -> `view`
- `create` -> `add`
- `update`, `partial_update` -> `change`
- `destroy` -> `delete`
- `bulk_create` -> `bulk_add`

`BloomerpModelViewSet` delegates queryset and field decisions to the resolver. It also checks unsaved create/update candidates through the Python compiler, strips denied response fields, rejects denied request fields, and applies nested queryset optimization.

When changing API access, test all affected dimensions: authentication class selection, row results, response fields, write fields, create/update candidate matching, nesting, and bulk-create fallback.

## UI, Services, and Other Boundaries

Permission-sensitive entrypoints still need their own enforcement. Useful current examples include:

- `bloomerp/django_bloomerp/bloomerp/views/generic/detail/base.py`
- `bloomerp/django_bloomerp/bloomerp/views/generic/model/create.py`
- `bloomerp/django_bloomerp/bloomerp/components/layout/render_layout_item.py`
- `bloomerp/django_bloomerp/bloomerp/components/objects/dataviews/dataview.py`
- `bloomerp/django_bloomerp/bloomerp/services/sectioned_layout_services.py`
- `bloomerp/django_bloomerp/bloomerp/services/file_permission_services.py`
- `bloomerp/django_bloomerp/bloomerp/services/sql_services.py`

Do not assume router registration, template hiding, or client-side state is authorization. Filter the server-side queryset and fields and protect the mutation entrypoint.

`AbstractBloomerpUser.get_content_types_for_user(...)` is a legacy Django-auth-only discovery helper. Use `UserPolicyManager.get_accessible_content_types(...)` where policy-aware discovery is required.

## Test Routing

- Managers, policy composition, global/row/field/object behavior: `tests/permissions/test_user_policy_manager.py` and `test_policy_manager.py`
- Filter compiler authorization: `tests/permissions/test_filter_authorization.py`
- Django, Python, and SQL compiler behavior: `tests/permissions/test_permission_compilers.py` and `test_sql_permission_compiler.py`
- Generated API behavior: relevant tests under `tests/api/` and `tests/views/api/`
- Component enforcement: matching endpoint tests under `tests/components/`
- Browser-only visibility or interaction: targeted tests under `tests/e2e/`

Extend the narrowest existing suite that exercises the real enforcement boundary.
