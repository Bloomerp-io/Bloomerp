"""Validate role placeholders and reusable placements accepted by the signing builder."""

from typing import Any

from rest_framework import serializers

from bloomerp.models.document_signing import SignatureLayoutField, SignatureLayoutRole


class SigningLayoutRoleSerializer(serializers.ModelSerializer):
    """Accept configurable roles without actual recipient identity details."""

    class Meta:
        model = SignatureLayoutRole
        fields = ("key", "label", "default_signing_order")


class SigningLayoutFieldSerializer(serializers.ModelSerializer):
    """Accept normalized field definitions assigned to a role key in the same payload."""

    role_key = serializers.SlugField(max_length=100)

    class Meta:
        model = SignatureLayoutField
        fields = (
            "key",
            "role_key",
            "field_type",
            "required",
            "page_number",
            "x",
            "y",
            "width",
            "height",
            "settings",
        )


class SigningPlacementSetSerializer(serializers.Serializer):
    """Validate the role and placement definitions shared by drafts and default layouts."""

    roles = SigningLayoutRoleSerializer(many=True, allow_empty=False, max_length=100)
    fields = SigningLayoutFieldSerializer(many=True, allow_empty=True, max_length=1000)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Reject duplicate keys and field assignments outside the submitted role set."""
        roles = [role["key"] for role in attrs["roles"]]
        fields = [field["key"] for field in attrs["fields"]]
        if len(roles) != len(set(roles)) or len(fields) != len(set(fields)):
            raise serializers.ValidationError("Role and field keys must be unique.")
        if any(field["role_key"] not in roles for field in attrs["fields"]):
            raise serializers.ValidationError(
                "Every field must belong to a submitted role."
            )
        return attrs


class SaveSigningLayoutSerializer(SigningPlacementSetSerializer):
    """Require a complete layout and an optimistic version token for replacing a default."""

    document_template_id = serializers.UUIDField()
    expected_layout_id = serializers.UUIDField(allow_null=True)
    fields = SigningLayoutFieldSerializer(many=True, allow_empty=False, max_length=1000)
