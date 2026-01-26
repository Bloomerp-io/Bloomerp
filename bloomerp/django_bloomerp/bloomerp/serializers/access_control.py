from bloomerp.models.access_control.policy import Policy
from rest_framework import serializers
from django.contrib.auth.models import Permission
from bloomerp.models.access_control.row_policy_rule import RowPolicyRule
from bloomerp.models.access_control.row_policy import RowPolicy
from bloomerp.models.access_control.field_policy import FieldPolicy
from django.db import transaction
from django.contrib.contenttypes.models import ContentType

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

