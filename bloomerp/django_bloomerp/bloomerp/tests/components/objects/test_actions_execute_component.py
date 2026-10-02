from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import Model
from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory

from bloomerp.components.files.items.preview import preview_file
from bloomerp.models import File
from bloomerp.models.definition import ObjectAction
from bloomerp.templatetags.bloomerp import render_object_action
from bloomerp.tests.base import (
    BloomerpComponentTestCase,
    ExpectedResult,
    RequestScenario,
)


class TestActionsExecuteComponent(BloomerpComponentTestCase):
    """Tests function `actions_execute` from `bloomerp/components/objects/actions.py`."""

    view_name = "components_objects_actions"

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Verify file previews target the drawer and retain server-side authorization."""
        file = File.objects.create(
            file=SimpleUploadedFile("preview.png", b"image"), persisted=True
        )
        kwargs = {
            "content_type_id": ContentType.objects.get_for_model(File).pk,
            "object_id": file.pk,
            "action_id": "view_file",
        }
        return [
            RequestScenario(
                name="View action renders preview into shared drawer",
                method="POST",
                user=self.admin_user,
                view_kwargs=kwargs,
                expected=ExpectedResult(
                    response_validators=[
                        self.contains_text("<img"),
                        self.header_equals(
                            "HX-Retarget", "#bloomerp-general-use-drawer-body"
                        ),
                    ]
                ),
            ),
            RequestScenario(
                name="View action denies a user without file access",
                method="POST",
                user=self.normal_user,
                view_kwargs=kwargs,
                expected=ExpectedResult(status_code=403),
            ),
        ]

    @staticmethod
    def empty_action(request: HttpRequest, object: Model) -> HttpResponse | None:
        """Supply a harmless callable for inspecting action button rendering."""
        return None

    def test_action_button_target_and_attributes(self) -> None:
        """
        Use case: An action specifies a response target and additional button attributes.
        Expected result: Rendering preserves the default and safely emits overrides.
        """
        # 1. Render an ordinary action with its existing default target.
        request = RequestFactory().get("/")
        request.user = self.admin_user
        object = self.create_customer("Action", "Target", 30)
        action = ObjectAction(
            id="example", label="Example", execution_func=self.empty_action
        )
        self.assertIn(
            'hx-target="#object-actions-target"',
            render_object_action(action, object, request),
        )
        # 2. Custom attributes are escaped and the explicit target is rendered.
        action.target = "#drawer-body"
        action.button_attrs = {
            "bloomerp-open-drawer": "drawer",
            "title": 'A "quoted" title',
        }
        markup = render_object_action(action, object, request)
        self.assertIn('hx-target="#drawer-body"', markup)
        self.assertIn('bloomerp-open-drawer="drawer"', markup)
        self.assertIn('title="A &quot;quoted&quot; title"', markup)
        # 3. The file action uses the preview component directly.
        self.assertIs(
            File.bloomerp_config.object_actions[0].execution_func, preview_file
        )
