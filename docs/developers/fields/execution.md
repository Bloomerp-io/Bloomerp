# Shared filter and row-policy execution

Use `FilterCondition` for a terminal comparison and `Filter` for an AND/OR group:

```python
from bloomerp.filters.definition import Filter, FilterCondition
from bloomerp.filters.manager import ModelFilterManager

predicate = Filter(connector="AND", conditions=[
    FilterCondition(field_path="age", lookup_id="greater_than", value=18),
    FilterCondition(field_path="country__name", lookup_id="equals", value="Belgium"),
])
queryset = ModelFilterManager(Customer).apply([predicate], queryset=authorized_customers)
```

The manager does not require a user or authorize filter dependencies. For user-policy requests, call `UserPolicyManager(user).validate_filters(Customer, groups)` before `apply()`. Validation returns `None` or raises `PermissionDenied`; malformed paths raise validation errors. It preserves the supplied queryset and combines groups with implicit AND. `filter(args, queryset=...)` parses GET parameters before calling `apply()`; it does not add authorization.

`resolve_condition()` resolves the terminal field and lookup and runs its form field's `clean()`. Both Q compilation and SQL compilation use this function. Nested lookups navigate only; they cannot be terminal predicates. Invalid conditions raise errors, including invalid conditions inside OR groups.

Lookup-local annotations are isolated in correlated subqueries so independent lookups and existing queryset annotations cannot overwrite each other.

## SQL

`compile_sql_filters(groups, model=Customer)` returns `CompiledSQL(clause, parameters)`. Execute the parameters separately from the SQL text. The predicate references the model's physical table name and includes a primary-key subquery when resolving joins; it is not an arbitrary-query security rewriter.

Native SQL compilation invokes the lookup's SQL factory. SQL collection/aggregate targets are rejected until their subquery/HAVING contract is implemented. Missing SQL factories are errors. The model compiler is not yet the workspace analytics executor.

## Row policies

`RowPolicyRuleContent` extends the same `Filter` model with permission grants:

```python
from bloomerp.permissions.definition import RowPolicyRuleContent

rule = RowPolicyRuleContent(
    **predicate.model_dump(),
    permissions=["view"],
)
all_rows = RowPolicyRuleContent(connector="AND", conditions=[], permissions=["view"])
```

Conditions are actual `FilterCondition` instances. Empty AND groups match all rows; empty OR groups match no rows. These semantics are identical for user filters and row policies. An empty user-filter list preserves its input queryset, while no applicable permission grant denies all rows.

The permission layer selects applicable rules, binds `$user`, and retains the relationship between each row predicate and its field grants. Django permission compilation delegates predicates to the shared Q compiler. Python evaluation reuses the same resolution/cleaning and the lookup's evaluator. SQL permissions retain their table rewriting and field masking, using shared Q predicates through the existing Django SQL generation path.

The legacy `__all__` sentinel becomes an empty AND group; it is not a supported `FilterCondition.field_path`. Mixed legacy OR groups containing both `__all__` and other conditions must be rewritten explicitly, rather than dropping conditions during normalization. Legacy field-ID/operator conditions remain accepted at the permission boundary and are normalized into field paths and lookup IDs. Newly saved rules use the shared shape. The existing permissions wizard receives a legacy presentation adapter until its UI is replaced. Existing stored JSON is normalized on read; no bulk data rewrite is performed. `RowPolicyRuleCondition` remains a legacy input adapter, and the misspelled `FilterCondition` remains an import alias for compatibility.

`validate_filters()` walks the same resolved field dependencies as compilation, checks model view grants, and requires field visibility across every row that can influence a predicate. Root fields may use conditional grants when every applicable row grant includes the field. Related rows require explicit unconditional view access; related fields require unconditional field coverage. This includes relation/count lookups whose path ends at the relation itself. Superusers bypass permission restrictions.

These checks deliberately reject some safe but complicated combinations of overlapping policies: they do not try to prove arbitrary predicates equivalent. They never inspect today's row contents to infer that access is unrestricted. Related-row scoping during execution is still future work.

The dataview calls validation after parsing and before applying filters. Other authorization adapters, including the API's public/model-defined access modes, must establish equivalent dependency checks before enabling filter execution; a restricted root queryset alone is insufficient.

## Query parameter parsing

`parse_filters(args, model=Customer)` returns `list[Filter]`. It accepts a mapping
or a Django `QueryDict`, preserving repeated values.

- `filter` contains a JSON list of groups, with explicit AND/OR connectors.
- Bare fields use the registered lookup whose expressions include `""`.
- `first_name_eq=David` and `first_name__exact=David` resolve registered lookup
  aliases to the canonical lookup ID (`equals`). No built-in alias table is needed.
- Complete field paths take precedence over suffixes. For ambiguous JSON keys,
  use the JSON filter format with separate `field_path` and `lookup_id` values.
- Shorthand conditions form one AND group, combined with JSON groups through
  implicit AND. Repeated shorthand values remain separate AND conditions;
  repeated `filter` parameters contribute all their groups.
- Dictionary list values remain a single lookup value. Use JSON groups for
  structured URL values or OR conditions. Parsing does not guess JSON in values.
- Common controls (`page`, `page_size`, `limit`, `offset`, `ordering`, `sort`,
  `q`, `search`, `format`, `_component_id`) are ignored. Endpoint-specific controls
  must be removed by the caller. Fields with reserved names can use JSON filters.
- Malformed JSON, unknown fields, and unsupported shorthand lookups raise Django
  `ValidationError`. Empty input and `filter=[]` return no groups; a blank `filter`
  is invalid. Lookup value cleaning and JSON field/lookup resolution happen during
  compilation, not deserialization.
