from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import Model
from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory

from bloomerp.components.files.items.preview import preview_file
from bloomerp.models import FileNode
from bloomerp.models.definition import ObjectAction
from bloomerp.templatetags.bloomerp import render_object_action
from bloomerp.tests.base import (
    BloomerpComponentTestCase,
    ExpectedResult,
    RequestScenario,
)


from bloomerp.tests.views.communication.voip.admin_fixtures import (
    VoIPAdministrationFixtures,
)
from unittest.mock import patch


class TestActionsExecuteComponent(
    VoIPAdministrationFixtures, BloomerpComponentTestCase
):
    """Tests function `actions_execute` from `bloomerp/components/objects/actions.py`."""

    view_name = "components_objects_actions"

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Verify file previews target the drawer and retain server-side authorization."""
        file = FileNode.objects.create(
            content=SimpleUploadedFile("preview.png", b"image"), kind="FILE"
        )
        kwargs = {
            "content_type_id": ContentType.objects.get_for_model(FileNode).pk,
            "object_id": file.pk,
            "action_id": "view_file",
        }
        return [
            RequestScenario(
                name="Queue VoIP sync with connection change policy",
                method="POST",
                user=self.normal_user,
                prepare=[self.prepare_voip_action, self.grant_connection_access],
                expected=ExpectedResult(response_validators=[self.verify_queued]),
            ),
            RequestScenario(
                name="Connection owner without change policy cannot sync",
                method="POST",
                user=self.normal_user,
                prepare=self.prepare_denied_action,
                expected=ExpectedResult(
                    status_code=403, response_validators=[self.verify_not_queued]
                ),
            ),
            RequestScenario(
                name="GET cannot synchronize carrier numbers",
                user=self.admin_user,
                prepare=self.prepare_voip_action,
                expected=ExpectedResult(
                    status_code=405, response_validators=[self.verify_not_queued]
                ),
            ),
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
            RequestScenario(
                name="GET executes an explicitly configured GET object action",
                user=self.admin_user,
                view_kwargs=kwargs,
                prepare=self.prepare_get_action,
                expected=ExpectedResult(response_validators=[self.contains_text("<img")]),
            ),
            RequestScenario(
                name="GET object actions reject POST",
                method="POST",
                user=self.admin_user,
                view_kwargs=kwargs,
                prepare=self.prepare_get_action,
                expected=ExpectedResult(status_code=405, response_validators=[
                    self.header_equals("Allow", "GET"),
                ]),
            ),
        ]

    def prepare_get_action(self, scenario: RequestScenario) -> None:
        """Configure the read-only file preview action to accept GET for one scenario."""
        actions = [
            action.model_copy(update={"method": "GET"})
            if isinstance(action, ObjectAction) and action.id == "view_file" else action
            for action in FileNode.bloomerp_config.object_actions
        ]
        self.enterContext(patch.object(FileNode.bloomerp_config, "object_actions", actions))

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
        self.assertEqual(action.method, "POST")
        self.assertIn('hx-post="', render_object_action(action, object, request))
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
        action.method = "GET"
        markup = render_object_action(action, object, request)
        self.assertIn('hx-get="', markup)
        self.assertNotIn('hx-post="', markup)
        self.assertNotIn("csrfmiddlewaretoken", markup)
        # 3. The file action uses the preview component directly.
        self.assertIs(
            FileNode.bloomerp_config.object_actions[0].execution_func, preview_file
        )

    def prepare_voip_action(self, scenario: RequestScenario) -> None:
        """Use the real generic action endpoint with a deterministic async dispatcher."""
        self.prepare_account(scenario)
        scenario.view_kwargs = {
            "content_type_id": ContentType.objects.get_for_model(self.connection).pk,
            "object_id": self.connection.pk,
            "action_id": "synchronize_numbers",
        }
        self.dispatch_job = self.enterContext(
            patch(
                "bloomerp.communication.builtins.voip.actions.run_async_or_sync",
                return_value=(True, None),
            )
        )

    def prepare_denied_action(self, scenario: RequestScenario) -> None:
        """Make an unprivileged user the creator to test the new permission contract."""
        self.prepare_voip_action(scenario)
        self.connection.created_by = self.normal_user
        self.connection.save()

    def verify_queued(self, response: HttpResponse) -> bool:
        """Verify only serializable identifiers cross the async boundary."""
        from bloomerp.communication.builtins.voip.actions import (
            synchronize_connection_job,
        )

        self.dispatch_job.assert_called_once_with(
            synchronize_connection_job, self.connection.pk, self.normal_user.pk
        )
        return "queued" in response.content.decode()

    def verify_not_queued(self, response: HttpResponse) -> bool:
        """Ensure denied actions never dispatch carrier work."""
        self.dispatch_job.assert_not_called()
        return True
