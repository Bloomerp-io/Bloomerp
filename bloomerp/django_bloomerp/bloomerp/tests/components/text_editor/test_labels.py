"""Shared-label mutation contracts and creator/admin editing permissions."""

from bloomerp.models import Label
from bloomerp.tests.base import (
    BloomerpComponentTestCase,
    ExpectedResult,
    RequestScenario,
)


class TestLabels(BloomerpComponentTestCase):
    """Test label creation, normalization, and real mutation authorization."""

    view_name = "components_text_editor_labels"
    auto_create_customers = False

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Cover creator editing, denied edits, admin overrides, and duplicate names."""
        owned = Label.objects.create(name="Owned", created_by=self.normal_user)
        other = Label.objects.create(name="Other", created_by=self.admin_user)
        return [
            RequestScenario(
                name="Requires login",
                method="POST",
                data={"name": "New"},
                expected=ExpectedResult(status_code=302),
            ),
            RequestScenario(
                name="User creates shared label",
                user=self.normal_user,
                method="POST",
                data={"name": " New "},
                expected=ExpectedResult(
                    status_code=201,
                    response_validators=self.json_key_equals("label", "New"),
                ),
            ),
            RequestScenario(
                name="Creator edits label",
                user=self.normal_user,
                method="POST",
                data={"label_id": owned.pk, "name": "Renamed"},
            ),
            RequestScenario(
                name="Other creator edit denied",
                user=self.normal_user,
                method="POST",
                data={"label_id": other.pk, "name": "Denied"},
                expected=ExpectedResult(status_code=403),
            ),
            RequestScenario(
                name="Admin edits any label",
                user=self.admin_user,
                method="POST",
                data={"label_id": owned.pk, "name": "Admin edit"},
            ),
            RequestScenario(
                name="Case-insensitive duplicate rejected",
                user=self.normal_user,
                method="POST",
                data={"name": " owned "},
                expected=ExpectedResult(status_code=409),
            ),
            RequestScenario(
                name="Invalid color rejected",
                user=self.normal_user,
                method="POST",
                data={"name": "Color", "color": "red"},
                expected=ExpectedResult(status_code=400),
            ),
        ]
