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

The manager does not require a user or authorize filter dependencies. It preserves the supplied queryset and combines groups with implicit AND. GET parsing remains unimplemented; `apply()` is the executable entry point for typed filters.

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

Filter-dependency authorization and permission-scoped related aggregates are separate work. Shared predicate compilation alone does not make an arbitrary user filter authorized.
