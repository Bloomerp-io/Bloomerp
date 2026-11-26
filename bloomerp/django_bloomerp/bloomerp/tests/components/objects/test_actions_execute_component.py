from bs4 import BeautifulSoup
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponse, StreamingHttpResponse
from django.test import RequestFactory
from django.urls import reverse

from bloomerp.components.files.items.preview import preview_file
from bloomerp.models import FileNode
from bloomerp.models.definition import (
    ObjectAction,
    ObjectActionContext,
    ObjectActionGrouping,
    ObjectDrawerAction,
    ObjectModalAction,
    get_object_actions,
)
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
        """Verify configured execution and direct file previews retain authorization."""
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
                    status_code=404, response_validators=[self.verify_not_queued]
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
                name="View action loads the preview endpoint",
                view_name="components_preview_file",
                user=self.admin_user,
                view_kwargs={"file_id": file.pk},
                expected=ExpectedResult(response_validators=[self.contains_text("<img")]),
            ),
            RequestScenario(
                name="View action denies a user without file access",
                view_name="components_preview_file",
                user=self.normal_user,
                view_kwargs={"file_id": file.pk},
                expected=ExpectedResult(status_code=403),
            ),
            RequestScenario(
                name="GET executes an explicitly configured action inside a group",
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
        """Install an executable GET action under a nested dropdown."""
        actions = [
            ObjectActionGrouping(id="more", actions=[
                ObjectActionGrouping(id="previews", actions=[
                    ObjectDrawerAction(
                        id="view_file", label="View", execution_func=self.preview_action,
                    ),
                ]),
            ]),
        ]
        self.enterContext(patch.object(FileNode.bloomerp_config, "object_actions", actions))

    @staticmethod
    def preview_action(context: ObjectActionContext) -> HttpResponse | StreamingHttpResponse:
        """Use the preview view as a contextual callback for the dispatch scenario."""
        return preview_file(context.request, context.object)

    @staticmethod
    def empty_action(context: ObjectActionContext) -> HttpResponse | None:
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
        action.button_attrs = {
            "hx-target": "#drawer-body",
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
        preview = next(
            action for action in get_object_actions(FileNode, surface="detail")
            if action.id == "view_file"
        )
        self.assertIsInstance(preview, ObjectDrawerAction)
        file = FileNode.objects.create(
            content=SimpleUploadedFile("preview.png", b"image"), kind="FILE",
        )
        markup = render_object_action(preview, file, request)
        url = reverse("components_preview_file", kwargs={"file_id": file.pk})
        self.assertIn(f'hx-get="{url}"', markup)
        self.assertIn('hx-target="#bloomerp-general-use-drawer-body"', markup)
        self.assertIn('hx-push-url="false"', markup)
        self.assertIn('bloomerp-open-drawer="bloomerp-general-use-drawer"', markup)
        self.assertIn('bloomerp-set-drawer-title-to="File preview"', markup)
        self.assertIn('bloomerp-set-drawer-size-to="xl"', markup)

    def test_modal_and_icon_only_buttons_render_in_dropdown(self) -> None:
        """Render a secondary group trigger and honor button attributes inside the menu."""
        request = RequestFactory().get("/")
        request.user = self.admin_user
        obj = self.create_customer("Grouped", "Action", 30)
        action = ObjectModalAction(
            id="review", icon="fa fa-eye", endpoint="/review/",
            title="Review", size="xl",
            button_attrs={"aria-label": "Review record", "hx-target": "#custom-modal-body"},
        )
        html = render_object_action(
            ObjectActionGrouping(id="more", actions=[action]), obj, request,
        )
        self.assertIsInstance(action, ObjectAction)
        trigger = BeautifulSoup(html, "html.parser").select_one('button[aria-label="More actions"]')
        self.assertIsNotNone(trigger)
        self.assertIn("btn-secondary", trigger.get("class", []))
        self.assertIn('aria-label="Review record"', html)
        self.assertIn('role="menuitem"', html)
        self.assertIn('hx-get="/review/"', html)
        self.assertIn('hx-target="#custom-modal-body"', html)
        self.assertIn('bloomerp-open-modal="bloomerp-general-use-modal"', html)
        self.assertIn('bloomerp-set-modal-title-to="Review"', html)
        self.assertIn('bloomerp-set-modal-size-to="xl"', html)

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
