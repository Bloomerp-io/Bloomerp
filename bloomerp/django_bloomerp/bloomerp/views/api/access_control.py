from rest_framework import serializers, viewsets, status
from bloomerp.models.access_control.policy import Policy
from bloomerp.serializers.access_control import (
    PolicySerializer,
)
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db import transaction

class PolicyViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing access control policies.

    Supports:
    - list
    - retrieve
    - create (nested row_policy + field_policy)
    """

    queryset = (
        Policy.objects
        .select_related("row_policy", "field_policy")
        .prefetch_related(
            "row_policy__rules__permissions",
        )
    )

    serializer_class = PolicySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """
        Optionally restrict policies based on the user.
        For now: return all policies.
        """
        return self.queryset

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        """
        Create a Policy with nested RowPolicy, RowPolicyRules and FieldPolicy.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        policy = serializer.save(
            created_by=request.user,
            updated_by=request.user,
        )

        headers = self.get_success_headers(serializer.data)
        return Response(
            self.get_serializer(policy).data,
            status=status.HTTP_201_CREATED,
            headers=headers,
        )
