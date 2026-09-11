from django.urls import reverse

from bloomerp.models import Sidebar
from bloomerp.tests.base import (
    BloomerpComponentTestCase,
    ExpectedResult,
    RequestScenario,
)


class TestSelectPreferenceComponent(BloomerpComponentTestCase):
    """Tests the preference-selection component."""

    view_name = "components_select_preference"

    def setUp(self) -> None:
        super().setUp()
        Sidebar.objects.create(
            user=self.admin_user,
            name="Primary",
            selected=True,
        )
        self.deletable = Sidebar.objects.create(
            user=self.admin_user,
            name="Temporary",
            selected=False,
        )

    def get_test_scenarios(self) -> list[RequestScenario]:
        delete_url_template = reverse(
            "components_delete_preference",
            kwargs={"model": "Sidebar", "preference_id": "REPLACE_WITH_ID"},
        )
        return [
            RequestScenario(
                name="render owner delete action",
                user=self.admin_user,
                view_kwargs={"model": "Sidebar"},
                headers={"HX-Request": "true"},
                expected=ExpectedResult(
                    response_validators=[
                        self.contains_text(
                            f'data-delete-preference="{self.deletable.pk}"'
                        ),
                        self.contains_text(delete_url_template),
                    ],
                ),
            )
        ]
