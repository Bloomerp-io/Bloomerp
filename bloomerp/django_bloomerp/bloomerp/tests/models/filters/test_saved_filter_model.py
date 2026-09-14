from django.core.exceptions import ValidationError

from bloomerp.models.filters.filter import SavedFilter
from bloomerp.tests.base import BloomerpModelTestCase, ModelScenario, ExpectedModelException


class TestSavedFilterModel(BloomerpModelTestCase):
    model = SavedFilter

    def get_test_scenarios(self):
        model = {"scope": "model", "identifier": "15", "name": "People"}
        workspace = {"scope": "workspace", "identifier": "42", "name": "People"}
        payload = [{"connector": "OR", "conditions": [{"field_path": "first_name", "lookup_id": "equals", "value": "David"}]}]
        invalid = [ExpectedModelException(phase="create", exception=ValidationError)]
        return [
            ModelScenario(
                name="Model preset defaults and update",
                description="UC: Create a model preset and edit its groups. Expected Result: Empty defaults and the same record on update.",
                create_args=model, create_validators=lambda record: record.filters == [] and str(record) == "People",
                update_args={"name": "Named people", "filters": payload},
                update_validators=lambda record: record.filters == payload and SavedFilter.objects.count() == 1,
            ),
            ModelScenario(
                name="Workspace preset stores grouped JSON", 
                create_args={**workspace, "filters": payload},
                create_validators=lambda record: record.scope == "workspace" and record.filters == payload),
            ModelScenario(
                name="Duplicate name in the same scope is rejected",
                preparation=lambda: SavedFilter.objects.create(**model), create_args=model, expected_exceptions=invalid),
            ModelScenario(
                name="Same name in another identifier is allowed",
                preparation=lambda: SavedFilter.objects.create(**model), create_args={**model, "identifier": "16"}),
            ModelScenario(
                name="Same name and identifier in another scope is allowed",
                preparation=lambda: SavedFilter.objects.create(**model), create_args={**workspace, "identifier": "15"}),
            ModelScenario(
                name="Unknown scope is rejected", 
                create_args={**model, "scope": "global"}, 
                expected_exceptions=invalid),
            ModelScenario(
                name="Malformed filter payload is rejected", 
                create_args={**workspace, "filters": {"connector": "AND"}}, expected_exceptions=invalid),
            ModelScenario(
                name="Invalid connector is rejected", 
                create_args={**model, "filters": [{"connector": "XOR", "conditions": []}]}, expected_exceptions=invalid),
            ModelScenario(
                name="Blank name is rejected", 
                create_args={**model, "name": " "}, 
                expected_exceptions=invalid
            ),
            ModelScenario(
                name="Blank identifier is rejected", 
                create_args={**model, "identifier": ""}, 
                expected_exceptions=invalid
            ),
        ]
