from bloomerp.tests.base import ExpectedResult, RequestScenario
from bloomerp.models.filters.filter import SavedFilter
from .preset_test_case import PresetComponentTestCase


class TestGetComponent(PresetComponentTestCase):
    view_name = "components_filters_get"

    def extendedSetup(self):
        super().extendedSetup()
        SavedFilter.objects.create(scope="model", identifier=str(self.workspace.pk), name="Other identifier", filters=[])

    def exact_preset(self, preset):
        expected = {"id": str(preset.pk), "scope": preset.scope, "identifier": preset.identifier,
                    "name": preset.name, "filters": preset.filters}
        return self._named_validator("exact_scoped_preset_payload", lambda response: response.json() == [expected])

    def get_test_scenarios(self):
        return [
            RequestScenario(
                name="List only the requested model scope", 
                user=self.admin_user,
                query_params=self.model_scope(), 
                expected=ExpectedResult(response_validators=self.exact_preset(self.preset))
            ),
            RequestScenario(
                name="List only the requested workspace scope", user=self.admin_user,
                query_params={"scope": "workspace", "identifier": str(self.workspace.pk)},
                expected=ExpectedResult(response_validators=self.exact_preset(self.workspace_preset))
            ),
            RequestScenario(
                name="Identifier is required", 
                user=self.admin_user, query_params={"scope": "model"}, 
                expected=ExpectedResult(status_code=400)
            ),
            RequestScenario(
                name="Unknown scope is rejected", 
                user=self.admin_user, 
                query_params={"scope": "global", "identifier": self.identifier}, 
                expected=ExpectedResult(status_code=400)
            ),
            RequestScenario(
                name="Inaccessible workspace is rejected", 
                user=self.normal_user,            
                query_params={"scope": "workspace", "identifier": str(self.workspace.pk)}, 
                expected=ExpectedResult(status_code=403)
            ),
        ]
