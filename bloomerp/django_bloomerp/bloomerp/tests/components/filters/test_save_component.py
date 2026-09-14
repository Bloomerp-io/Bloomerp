from bloomerp.tests.base import ExpectedResult, RequestScenario
from bloomerp.models.workspaces.workspace import Workspace
from .preset_test_case import PresetComponentTestCase


class TestSaveComponent(PresetComponentTestCase):
    view_name = "components_filters_save"

    def extendedSetup(self):
        super().extendedSetup()
        self.other_workspace = Workspace.objects.create(user=self.admin_user, name="Other preset workspace")

    def scenario(self, name, data, status=200, validator=None, user=None):
        return RequestScenario(name=name, method="POST", user=user or self.admin_user,
                               data=data, content_type="application/json",
                               expected=ExpectedResult(status_code=status, response_validators=validator))

    def get_test_scenarios(self):
        payload = {**self.model_scope(), "name": "New preset", "filters": self.groups}
        return [
            self.scenario("Without ID creates a scoped preset", payload, 201, self.saved_count_and_name(3, "New preset")),
            self.scenario("Existing ID updates rather than duplicates",
                          {**payload, "filter_id": str(self.preset.pk)}, 200, self.saved_count_and_name(2, "New preset", self.preset.pk)),
            self.scenario("Workspace save creates a preset without a default",
                          {"scope": "workspace", "identifier": str(self.workspace.pk), "name": "Another", "filters": []},
                          201, self.saved_count_and_name(3, "Another")),
            self.scenario("A saved ID cannot move across scopes",
                          {**payload, "filter_id": str(self.workspace_preset.pk)}, 404),
            self.scenario("A saved ID cannot move across identifiers",
                          {**payload, "scope": "workspace", "identifier": str(self.other_workspace.pk), "filter_id": str(self.workspace_preset.pk), "filters": []}, 404),
            self.scenario("Duplicate name in the same scope is rejected", {**payload, "name": self.preset.name}, 400),
            self.scenario("Explicit empty ID does not create a duplicate", {**payload, "filter_id": None}, 400),
            self.scenario("Malformed JSON groups are rejected", {**payload, "filters": {}}, 400),
            self.scenario("Unknown fields are rejected", {**payload, "filters": [{"connector": "AND", "conditions": [{"field_path": "secret", "lookup_id": "equals", "value": "x"}]}]}, 400),
            self.scenario("Unknown lookups are rejected", {**payload, "filters": [{"connector": "AND", "conditions": [{"field_path": "first_name", "lookup_id": "unknown", "value": "x"}]}]}, 400),
            self.scenario("Invalid typed values are rejected", {**payload, "filters": [{"connector": "AND", "conditions": [{"field_path": "age", "lookup_id": "equals", "value": "invalid"}]}]}, 400),
            self.scenario("Inaccessible scope is rejected", {**payload, "scope": "workspace", "identifier": str(self.workspace.pk)}, 403, user=self.normal_user),
        ]
