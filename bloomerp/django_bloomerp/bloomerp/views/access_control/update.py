"""
This view allows users to update an access control policy using the
same mechanism as the create view, but with the data pre-filled.

A lot of the logic is therefore reused.
"""

from django.contrib.contenttypes.models import ContentType

from bloomerp.models.access_control.policy import Policy
from bloomerp.router import router
from bloomerp.views.access_control.manage_permissions import (
    FIELD_POLICIES_KEY,
    FIELD_POLICY_NAME_KEY,
    GLOBAL_PERMISSIONS_KEY,
    POLICY_DESCRIPTION_KEY,
    POLICY_NAME_KEY,
    ROW_POLICY_NAME_KEY,
    ROW_POLICY_RULES_KEY,
    ManageAccessControlForModelView,
)
from bloomerp.views.detail.base_detail import BloomerpBaseDetailView

@router.register(
    path="update",
    name="Update",
    description="Update this policy",
    route_type="detail",
    models=Policy,
)
class UpdatePolicyView(ManageAccessControlForModelView, BloomerpBaseDetailView):
    model = Policy

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.object : Policy = self.get_object()
        self.session_key = f"access_control_wizard_policy_{self.object.pk}"
        self.orchestrator = self.state_orchestrator_cls(request=request, session_key=self.session_key)
        self._initialize_wizard_state()

    def _initialize_wizard_state(self) -> None:
        if self.orchestrator.get_all_session_data():
            return

        row_policy_rules = [
            {
                "rule": dict(rule.rule or {}),
                "permissions": list(rule.permissions.order_by("codename").values_list("codename", flat=True)),
            }
            for rule in self.object.row_policy.rules.all().prefetch_related("permissions")
        ]

        self.orchestrator.set_session_data(
            GLOBAL_PERMISSIONS_KEY,
            list(self.object.global_permissions.order_by("codename").values_list("codename", flat=True)),
        )
        self.orchestrator.set_session_data(ROW_POLICY_NAME_KEY, self.object.row_policy.name or "")
        self.orchestrator.set_session_data(ROW_POLICY_RULES_KEY, row_policy_rules)
        self.orchestrator.set_session_data(FIELD_POLICY_NAME_KEY, self.object.field_policy.name or "")
        self.orchestrator.set_session_data(FIELD_POLICIES_KEY, dict(self.object.field_policy.rule or {}))
        self.orchestrator.set_session_data(POLICY_NAME_KEY, self.object.name or "")
        self.orchestrator.set_session_data(POLICY_DESCRIPTION_KEY, self.object.description or "")

    def get_policy_content_type(self) -> ContentType:
        return self.object.row_policy.content_type

    def get_policy_model(self):
        return self.get_policy_content_type().model_class()

    def save_policy(self, payload: dict):
        serializer = self.get_serializer(payload)
        if not serializer.is_valid():
            return self.serializer_error_to_wizard_error(serializer.errors)

        return serializer.save(updated_by=self.request.user)

    def get_serializer(self, payload: dict):
        return self._serializer_class(instance=self.object, data=payload)

    @property
    def _serializer_class(self):
        from bloomerp.serializers.access_control import PolicySerializer

        return PolicySerializer
