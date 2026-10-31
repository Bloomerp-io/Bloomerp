"""Accept generic role-based document preparation without real recipient details."""

from rest_framework import serializers

from bloomerp.serializers.signing_layout import SigningPlacementSetSerializer


class SaveSigningPreparationSerializer(SigningPlacementSetSerializer):
    """Validate a complete editable preparation and its optimistic revision token."""

    id = serializers.UUIDField()
    revision = serializers.IntegerField(min_value=0)
    title = serializers.CharField(max_length=255)
    source_layout = serializers.UUIDField(allow_null=True, default=None)
