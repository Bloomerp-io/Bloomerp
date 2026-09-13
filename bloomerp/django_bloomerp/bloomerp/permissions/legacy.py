"""Translate stored pre-unification row conditions at the permissions boundary."""
from bloomerp.filters.definition import FilterCondition


def normalize_condition(value):
    """Return a shared condition (None for __all__) and an optional source scope."""
    if isinstance(value, FilterCondition):
        return value, None
    data = value.model_dump() if hasattr(value, "model_dump") else dict(value)
    if "field_path" in data or "lookup_id" in data:
        return FilterCondition.model_validate(data), None
    if data.get("field") == "__all__" or data.get("application_field_id") == "__all__":
        return None, None
    field_path = str(data.get("field") or "").replace(".", "__")
    content_type_id = None
    if data.get("application_field_id") not in (None, ""):
        from bloomerp.models.application_field import ApplicationField
        try:
            field = ApplicationField.objects.get(pk=data["application_field_id"])
        except (ApplicationField.DoesNotExist, ValueError, TypeError) as exc:
            raise ValueError("Unknown legacy application field") from exc
        content_type_id = field.content_type_id
        if field_path and field_path.split("__", 1)[0] != field.field:
            raise ValueError("Field name does not match application field")
        field_path = field_path or field.field
    operator = data.get("operator")
    operator = getattr(operator, "id", operator)
    if not field_path or not operator:
        raise ValueError("A row condition requires a field and lookup")
    from bloomerp.lookups.registry import LOOKUP_REGISTRY
    aliases = {
        alias: lookup.id for lookup in LOOKUP_REGISTRY.values()
        for alias in (lookup.id, *lookup.expressions)
    }
    if operator.startswith("__"):
        parts = operator.lstrip("_").split("__")
        lookup_id = aliases.get(parts[-1])
        if lookup_id:
            parts.pop()
        field_path, operator = "__".join(parts), lookup_id or "equals"
    else:
        operator = aliases.get(operator, operator)
    return FilterCondition(field_path=field_path, lookup_id=operator, value=data.get("value")), content_type_id


def editor_rule(rule, model):
    """Keep the existing permissions wizard readable until its UI is replaced."""
    from bloomerp.models.application_field import ApplicationField
    from bloomerp.permissions.definition import RowPolicyRuleContent
    from bloomerp.lookups.registry import LOOKUP_REGISTRY

    normalized = RowPolicyRuleContent.model_validate(rule)
    if normalized.connector == "AND" and not normalized.conditions:
        conditions = [{"field": "__all__", "application_field_id": "__all__"}]
    else:
        fields = {field.field: field for field in ApplicationField.get_for_model(model)}
        conditions = []
        for condition in normalized.conditions:
            root = condition.field_path.split("__", 1)[0]
            operator = condition.lookup_id
            if "__" in condition.field_path:
                lookup = next(item for item in LOOKUP_REGISTRY.values() if item.id == condition.lookup_id)
                suffix = lookup.expressions[0]
                operator = "__" + condition.field_path + ("__" + suffix if suffix else "")
            conditions.append({
                "application_field_id": fields[root].pk,
                "field": root,
                "operator": operator,
                "value": condition.value,
            })
    return {"connector": normalized.connector, "conditions": conditions}
