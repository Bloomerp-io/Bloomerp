from bloomerp.models.access_control.policy import Policy
from rest_framework import serializers
from django.contrib.auth.models import Permission
from bloomerp.models.access_control.row_policy_rule import ROW_POLICY_DISALLOWED_FIELD_TYPE_IDS, RowPolicyRule, RowPolicyRuleContent
from bloomerp.models.access_control.row_policy import RowPolicy
from bloomerp.models.access_control.field_policy import FieldPolicy
from bloomerp.models.application_field import ApplicationField
from django.db import transaction
from django.core.exceptions import ValidationError as DjangoValidationError
from django.contrib.contenttypes.models import ContentType
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from pydantic import ValidationError as PydanticValidationError


@extend_schema_field(OpenApiTypes.STR)
class PermissionCodenameField(serializers.RelatedField):
    def to_representation(self, value: Permission):
        return value.codename

    def to_internal_value(self, data):
        try:
            return Permission.objects.get(codename=data)
        except Permission.DoesNotExist:
            raise serializers.ValidationError(f"Invalid permission codename: {data}")


class RowPolicyRuleSerializer(serializers.ModelSerializer):
    permissions = PermissionCodenameField(
        many=True,
        queryset=Permission.objects.all()
    )

    class Meta:
        model = RowPolicyRule
        fields = [
            "id",
            "rule",
            "permissions",
        ]

    def validate_rule(self, value):
        try:
            RowPolicyRuleContent.model_validate(value)
            # Preserve legacy source IDs until the parent validates their scope.
            return value
        except PydanticValidationError as exc:
            raise serializers.ValidationError(str(exc)) from exc


class RowPolicySerializer(serializers.ModelSerializer):
    rules = RowPolicyRuleSerializer(many=True)

    class Meta:
        model = RowPolicy
        fields = [
            "id",
            "name",
            "rules",
        ]


class FieldPolicySerializer(serializers.ModelSerializer):
    rules = serializers.JSONField(source="rule")

    class Meta:
        model = FieldPolicy
        fields = [
            "id",
            "name",
            "rules",
        ]


class PolicySerializer(serializers.ModelSerializer):
    content_type_id = serializers.IntegerField(write_only=True)
    row_policy = RowPolicySerializer()
    field_policy = FieldPolicySerializer()
    global_permissions = PermissionCodenameField(
        many=True,
        queryset=Permission.objects.all(),
        required=False
    )

    class Meta:
        model = Policy
        fields = [
            "name",
            "description",
            "content_type_id",
            "global_permissions",
            "row_policy",
            "field_policy",
        ]
        
    def validate(self, attrs):
        global_permissions = attrs.get("global_permissions", [])
        allowed_permission_codenames = {permission.codename for permission in global_permissions}
        content_type_id = attrs.get("content_type_id")
        if content_type_id is None and self.instance is not None:
            content_type_id = self.instance.row_policy.content_type_id

        row_policy = attrs.get("row_policy") or {}
        row_policy_rules = row_policy.get("rules", [])
        invalid_row_permissions = sorted(
            {
                permission.codename
                for rule in row_policy_rules
                for permission in rule.get("permissions", [])
                if permission.codename not in allowed_permission_codenames
            }
        )

        field_policy = attrs.get("field_policy") or {}
        field_policy_rules = field_policy.get("rule", {})
        invalid_field_permissions = sorted(
            {
                str(permission_codename)
                for permission_list in field_policy_rules.values()
                for permission_codename in permission_list
                if str(permission_codename) not in allowed_permission_codenames
            }
        )

        errors = {}
        if invalid_row_permissions:
            errors["row_policy"] = [
                "Row policy permissions must also be selected as global permissions."
            ]
        invalid_row_policy_field_ids = self._get_invalid_row_policy_field_ids(
            content_type_id,
            row_policy_rules,
        )
        if invalid_row_policy_field_ids:
            errors["row_policy"] = [
                "Properties and one-to-many fields cannot be used in row policies."
            ]
        if invalid_field_permissions:
            errors["field_policy"] = [
                "Field policy permissions must also be selected as global permissions."
            ]

        if errors:
            raise serializers.ValidationError(errors)

        if content_type_id:
            for row_rule in row_policy_rules:
                candidate = RowPolicyRule(
                    row_policy=RowPolicy(content_type_id=content_type_id),
                    rule=row_rule["rule"],
                )
                try:
                    candidate.validate_rule()
                    request = self.context.get("request")
                    if request is not None:
                        from bloomerp.permissions.manager import UserPolicyManager
                        UserPolicyManager(request.user).validate_filters(candidate.content_type, [RowPolicyRuleContent.model_validate(row_rule["rule"])])
                    row_rule["rule"] = RowPolicyRuleContent.model_validate(row_rule["rule"]).model_dump(exclude={"permissions"})
                except (DjangoValidationError, PydanticValidationError, ValueError) as exc:
                    raise serializers.ValidationError({"row_policy": str(exc)}) from exc
        return attrs

    def _get_invalid_row_policy_field_ids(self, content_type_id, row_policy_rules) -> set[str]:
        if not content_type_id:
            return set()

        disallowed_field_ids = {
            str(field_id)
            for field_id in ApplicationField.objects.filter(
                content_type_id=content_type_id,
                field_type__in=ROW_POLICY_DISALLOWED_FIELD_TYPE_IDS,
            ).values_list("id", flat=True)
        }
        if not disallowed_field_ids:
            return set()

        disallowed_names = dict(ApplicationField.objects.filter(
            content_type_id=content_type_id, pk__in=disallowed_field_ids,
        ).values_list("field", "pk"))
        invalid_field_ids = set()
        for rule in row_policy_rules:
            rule_content = (rule or {}).get("rule") or {}
            conditions = rule_content.get("conditions", []) if isinstance(rule_content, dict) else []
            for condition in conditions:
                if not isinstance(condition, dict):
                    continue
                root = str(condition.get("field_path", "")).split("__", 1)[0]
                if root in disallowed_names:
                    invalid_field_ids.add(str(disallowed_names[root]))
                application_field_id = str(condition.get("application_field_id", "")).strip()
                if application_field_id and application_field_id != "__all__" and application_field_id in disallowed_field_ids:
                    invalid_field_ids.add(application_field_id)

        return invalid_field_ids
        
    
    @transaction.atomic
    def create(self, validated_data):
        content_type_id = validated_data.pop("content_type_id")
        content_type = ContentType.objects.get(id=content_type_id)

        row_policy_data = validated_data.pop("row_policy")
        field_policy_data = validated_data.pop("field_policy")
        global_permissions = validated_data.pop("global_permissions", [])

        # Create RowPolicy (inherits content type)
        rules_data = row_policy_data.pop("rules")
        row_policy = RowPolicy.objects.create(
            content_type=content_type,
            **row_policy_data
        )

        for rule_data in rules_data:
            permissions = rule_data.pop("permissions")
            rule = RowPolicyRule.objects.create(
                row_policy=row_policy,
                **rule_data
            )
            rule.permissions.set(permissions)

        # Create FieldPolicy (inherits content type)
        field_policy = FieldPolicy.objects.create(
            content_type=content_type,
            **field_policy_data
        )

        # Create Policy
        policy = Policy.objects.create(
            row_policy=row_policy,
            field_policy=field_policy,
            **validated_data
        )

        if global_permissions:
            policy.global_permissions.set(global_permissions)

        return policy

    @transaction.atomic
    def update(self, instance, validated_data):
        content_type_id = validated_data.pop("content_type_id", None)
        content_type = instance.row_policy.content_type
        if content_type_id:
            requested_content_type = ContentType.objects.get(id=content_type_id)
            if requested_content_type != content_type:
                raise serializers.ValidationError(
                    {"content_type_id": ["Updating a policy to a different content type is not supported."]}
                )

        row_policy_data = validated_data.pop("row_policy")
        field_policy_data = validated_data.pop("field_policy")
        global_permissions = validated_data.pop("global_permissions", [])

        row_rules_data = row_policy_data.pop("rules", [])
        row_policy = instance.row_policy
        row_policy.name = row_policy_data.get("name", row_policy.name)
        row_policy.save(update_fields=["name"])
        row_policy.rules.all().delete()

        for rule_data in row_rules_data:
            permissions = rule_data.pop("permissions")
            rule = RowPolicyRule.objects.create(
                row_policy=row_policy,
                **rule_data,
            )
            rule.permissions.set(permissions)

        field_policy = instance.field_policy
        field_policy.name = field_policy_data.get("name", field_policy.name)
        field_policy.rule = field_policy_data.get("rule", field_policy.rule)
        field_policy.save(update_fields=["name", "rule"])

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        instance.global_permissions.set(global_permissions)

        return instance
