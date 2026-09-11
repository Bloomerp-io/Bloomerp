from django.urls import reverse

from bloomerp.models import Sidebar, User
from bloomerp.tests.base import (
    BloomerpComponentTestCase,
    ExpectedResult,
    RequestScenario,
)


class TestDeletePreferenceComponent(BloomerpComponentTestCase):
    """Tests deleting an owned preference through the component endpoint."""

    view_name = "components_delete_preference"

    def setUp(self) -> None:
        super().setUp()
        self.owner = User.objects.create_user(
            username="preference-owner",
            password="testpass123",
        )
        self.other_user = User.objects.create_user(
            username="preference-other",
            password="testpass123",
        )
        Sidebar.objects.create(user=self.owner, name="Primary", selected=True)
        self.deletable = Sidebar.objects.create(
            user=self.owner,
            name="Temporary",
            selected=False,
        )
        source = Sidebar.objects.create(user=self.other_user, name="Shared")
        self.reference = Sidebar.objects.create(
            user=self.owner,
            name="Reference",
            source_object=source,
        )

    def get_test_scenarios(self) -> list[RequestScenario]:
        headers = {"HX-Request": "true"}
        deletable_kwargs = {
            "model": "Sidebar",
            "preference_id": self.deletable.pk,
        }
        return [
            RequestScenario(
                name="render deletion confirmation",
                user=self.owner,
                view_kwargs=deletable_kwargs,
                headers=headers,
                expected=ExpectedResult(
                    response_validators=[
                        self.contains_text(
                            f'action="{reverse(self.view_name, kwargs=deletable_kwargs)}"'
                        ),
                        self.contains_text('hx-post="'),
                        self.contains_text("Temporary"),
                        self.contains_text("This action cannot be undone."),
                        self._preference_exists(self.deletable.pk),
                    ],
                ),
            ),
            RequestScenario(
                name="reject unsupported method",
                method="PUT",
                user=self.owner,
                view_kwargs=deletable_kwargs,
                headers=headers,
                expected=ExpectedResult(
                    status_code=405,
                    response_validators=self._preference_exists(self.deletable.pk),
                ),
            ),
            RequestScenario(
                name="owner deletes preference",
                method="POST",
                user=self.owner,
                view_kwargs=deletable_kwargs,
                headers=headers,
                expected=ExpectedResult(
                    response_validators=[
                        self.header_equals("HX-Refresh", "true"),
                        self._preference_does_not_exist(self.deletable.pk),
                    ],
                ),
            ),
            RequestScenario(
                name="reject deletion by another user",
                method="POST",
                user=self.other_user,
                view_kwargs=deletable_kwargs,
                headers=headers,
                expected=ExpectedResult(
                    status_code=403,
                    response_validators=self._preference_exists(self.deletable.pk),
                ),
            ),
            RequestScenario(
                name="reject deletion of derived reference",
                method="POST",
                user=self.owner,
                view_kwargs={
                    "model": "Sidebar",
                    "preference_id": self.reference.pk,
                },
                headers=headers,
                expected=ExpectedResult(
                    status_code=403,
                    response_validators=self._preference_exists(self.reference.pk),
                ),
            ),
        ]

    def _preference_exists(self, preference_id):
        return self._named_validator(
            f"preference_exists({preference_id!r})",
            lambda _response: Sidebar.objects.filter(pk=preference_id).exists(),
        )

    def _preference_does_not_exist(self, preference_id):
        return self._named_validator(
            f"preference_does_not_exist({preference_id!r})",
            lambda _response: not Sidebar.objects.filter(pk=preference_id).exists(),
        )
