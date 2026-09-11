from unittest.mock import patch

from bloomerp.tests.base import (
    BloomerpComponentTestCase,
    ExpectedResult,
    RequestScenario,
)


class TestObjectPreviewComponent(BloomerpComponentTestCase):
    """Tests function `object_preview` from `bloomerp/components/objects/details/object_preview.py`."""

    view_name = "components_object_preview"

    def get_test_scenarios(self) -> list[RequestScenario]:
        customer = self.CustomerModel.objects.first()
        content_type = self.get_content_type_for_model(self.CustomerModel)
        view_kwargs = {
            "content_type_id": content_type.pk,
            "object_id": customer.pk,
        }

        return [
            RequestScenario(
                name="authorized user",
                description="An authorized user can preview the object.",
                user=self.admin_user,
                view_kwargs=view_kwargs,
                expected=ExpectedResult(
                    response_validators=self.contains_text(str(customer)),
                ),
            ),
            RequestScenario(
                name="user without direct access",
                description="A user without direct access sees an explanatory message.",
                user=self.normal_user,
                view_kwargs=view_kwargs,
                expected=ExpectedResult(
                    response_validators=self.contains_text(
                        "You do not have direct access to this object."
                    ),
                ),
            ),
            RequestScenario(
                name="field rendering failure",
                description="A broken field renderer does not break the object preview.",
                user=self.admin_user,
                view_kwargs=view_kwargs,
                prepare=self._break_field_renderer,
                expected=ExpectedResult(
                    response_validators=self.contains_text(
                        "Preview is not available for this field."
                    ),
                ),
            ),
        ]

    def _break_field_renderer(self, _setup: RequestScenario) -> None:
        field_renderer_patch = patch(
            "bloomerp.templatetags.bloomerp.build_crud_layout_field_context",
            side_effect=RuntimeError("broken preview field"),
        )
        field_renderer_patch.start()
        self.addCleanup(field_renderer_patch.stop)
