"""Canonical row-rule payloads for the permission editor and its submissions."""
from django.core.exceptions import ValidationError
from pydantic import ValidationError as SchemaValidationError

from bloomerp.permissions.definition import RowPolicyRuleContent


def editor_rules(entries, content_type, *, user=None):
    if not isinstance(entries, list):
        raise ValidationError("Expected a list of row policy rules")
    result = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("permissions"), list):
            raise ValidationError("Invalid row policy entry")
        try:
            raw = entry["rule"]
            if not isinstance(raw, dict):
                raise ValueError("Expected one condition group")
            if "conditions" not in raw and ("field" in raw or "application_field_id" in raw):
                raw = {"connector": "AND", "conditions": [raw]}
            if "conditions" not in raw and raw.get("match_all") is not True:
                raise ValueError("Missing row policy conditions")
            rule = RowPolicyRuleContent.model_validate(raw)
        except (SchemaValidationError, ValueError, TypeError, KeyError) as exc:
            raise ValidationError("Invalid row policy conditions") from exc
        if rule._legacy_content_type_ids - {content_type.pk}:
            raise ValidationError("Field belongs to a different content type")
        payload = rule.model_dump(mode="json", exclude={"permissions"})
        if user is not None:
            from bloomerp.models.access_control.row_policy import RowPolicy
            from bloomerp.models.access_control.row_policy_rule import RowPolicyRule
            from bloomerp.permissions.manager import UserPolicyManager

            UserPolicyManager(user).validate_filters(content_type, [rule])
            RowPolicyRule(row_policy=RowPolicy(content_type=content_type), rule=payload).validate_rule()
        result.append({"rule": payload, "permissions": entry["permissions"]})
    return result
