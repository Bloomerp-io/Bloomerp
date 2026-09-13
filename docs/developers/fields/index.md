# BloomERP Field Types and Lookups

As the extensibility lies at the core of the BloomERP framework, it introduces a registry system for both fields and lookups, so that you as the developer can extend the framework to your liking. In essence, a field type describes a kind of data, whilst a lookup describes a condition that can be applied to that data.

For example, `CharField` supports `equals` and `contains`. A developer can add another lookup, attach it to that field type, and let the filter UI discover its label and input.

Field Types form an import part of the BloomERP framework as they are used accross the entire framework:
    - Permissions
    - Filtering
    - Form representation
    - Dataview representation

## Start here

- [Field types](field-type.md): declare available lookups and understand model versus analytics fields.
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

The intended execution flow is:

```text
Selected field + lookup + value
    → resolve the field and supported lookup
    → validate the value
    → invoke the terminal lookup's factory
    → combine predicates
    → execute within the permitted data
```

Nested lookups only navigate to another field. Terminal lookups produce predicates. The browser receives field identifiers, labels, lookup metadata, and editor HTML; it does not receive Python context objects.

## Review questions

When reading the lookup example, consider:

1. Can you tell what a factory receives and what it must return?
2. Does an operator need field metadata, or only its input value?
3. Is it clear which behavior belongs to the framework rather than the extension?

The [remaining API decisions](lookups.md#remaining-api-decisions) are listed separately from the implemented interfaces.
