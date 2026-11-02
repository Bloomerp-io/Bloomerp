# BloomERP Field Types and Lookups

A field type describes data and its editors; a lookup describes a condition
such as `equals` or `contains`. Registered types and lookups are shared by
permissions, filters, forms, and dataviews.

## Start here

- [File Reference](file-field.md): configure uploads, persistence, and file provenance.
- [Field types](field-type.md): declare available lookups and understand model versus analytics fields.
- [Filter editor](filter-editor.md): embed controls and share filters across workspace tiles.
- [Shared execution](execution.md): use typed filters and row-policy predicates.
- [Writing a lookup](lookups.md): build an input, compile a condition, and register an operator.

## Responsibilities

| Part | Responsibility |
| --- | --- |
| Field type | Declare supported lookups and default input behavior. |
| Lookup | Describe the operator, its input, and its supported execution backends. |
| Field resolver | Resolve a selected path to field metadata and an execution target. |
| Filter UI | Select fields and lookups, collect values, and maintain groups. |
| Filter compiler | Clean values and compile typed model conditions through registered factories. |
| Permission manager | Select applicable grants and enforce access. |

The execution flow is:

```text
Selected field + lookup + value
    → resolve the field and supported lookup
    → validate the value
    → invoke the terminal lookup's factory
    → combine predicates
    → execute within the permitted data
```

Nested lookups only navigate to another field. Terminal lookups produce predicates. The browser receives field identifiers, labels, lookup metadata, and editor HTML; it does not receive Python context objects.
