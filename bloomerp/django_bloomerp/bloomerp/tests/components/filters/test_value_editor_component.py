"""Value editor rendering and restoration through the scoped POST endpoint."""
import re
from datetime import timedelta
from html import unescape
from unittest import skip
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.template.loader import render_to_string
from django.test import RequestFactory
from django.utils import timezone

from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from bloomerp.permissions.definition import (
    AccessRule,
    PermissionToken,
    RowPolicyRuleContent,
)
from bloomerp.tests.base import (
    BloomerpComponentTestCase,
    ExpectedResult,
    RequestScenario,
)

from .validators import response_has_widget, widget_has_input


class TestValueEditorComponent(BloomerpComponentTestCase):
    """Check widget behavior without depending on HTML attribute order or styling."""

    view_name = "components_filters_value_editor"
    create_foreign_models = True

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Cover value restoration and model-scoped authorization for editor requests."""
        model_params = {
            "scope": "model",
            "id": self.get_content_type_for_model(self.CustomerModel).pk,
            "field_path": "first_name",
            "lookup_id": "equals",
        }
        scenarios = [
            RequestScenario(
                name="A model-scoped token authorizes the JSON value-editor POST",
                method="POST", user=self.normal_user, content_type="application/json",
                data=model_params, prepare=self.attach_view_token,
                expected=ExpectedResult(response_validators=[response_has_widget, widget_has_input(name="value", type="text")]),
            ),
            RequestScenario(
                name="The same user cannot load the value editor without the token",
                method="POST", user=self.normal_user, content_type="application/json",
                data=model_params, expected=ExpectedResult(status_code=403),
            ),
            RequestScenario(
                name="EDITOR: Text equality renders a named text input",
                method="POST",
                user=self.admin_user,
                content_type="application/json",
                data=model_params,
                expected=ExpectedResult(response_validators=[
                    response_has_widget,
                    widget_has_input(name="value", type="text"),
                ]),
            ),
            RequestScenario(
                name="RESTORE: Text restores quotes and markup as input data",
                method="POST",
                user=self.admin_user,
                content_type="application/json",
                data={**model_params, "value": 'David "<example>" & friends'},
                expected=ExpectedResult(response_validators=[
                    response_has_widget,
                    widget_has_input(name="value", value='David "<example>" & friends'),
                ]),
            ),
            RequestScenario(
                name="EDITOR: Numeric field renders a number input and preserves zero",
                method="POST",
                user=self.admin_user,
                content_type="application/json",
                data={**model_params, "field_path": "age", "value": 0},
                expected=ExpectedResult(response_validators=[
                    response_has_widget,
                    widget_has_input(name="value", type="number", value="0"),
                ]),
            ),
            RequestScenario(
                name="RESTORE: Date input restores an ISO date",
                method="POST",
                user=self.admin_user,
                content_type="application/json",
                data={**model_params, "field_path": "date_joined", "value": "2026-09-13"},
                expected=ExpectedResult(response_validators=[
                    response_has_widget,
                    widget_has_input(name="value", type="date", value="2026-09-13"),
                ]),
            ),
            RequestScenario(
                name="LOOKUP: Is-null overrides a text field with a boolean editor",
                method="POST",
                user=self.admin_user,
                content_type="application/json",
                data={**model_params, "lookup_id": "is_null", "value": True},
                expected=ExpectedResult(response_validators=[
                    response_has_widget,
                    widget_has_input(name="value", type="checkbox", checked=True),
                ]),
            ),
            RequestScenario(
                name="RESTORE: False leaves the boolean editor unchecked",
                method="POST",
                user=self.admin_user,
                content_type="application/json",
                data={**model_params, "lookup_id": "is_null", "value": False},
                expected=ExpectedResult(response_validators=[
                    response_has_widget,
                    widget_has_input(name="value", type="checkbox", checked=False),
                ]),
            ),
            RequestScenario(
                name="NESTED: Related text field uses its terminal lookup editor",
                method="POST",
                user=self.admin_user,
                content_type="application/json",
                data={**model_params, "field_path": "country__name", "value": "Belgium"},
                expected=ExpectedResult(response_validators=[
                    response_has_widget,
                    widget_has_input(name="value", type="text", value="Belgium"),
                ]),
            ),
            RequestScenario(
                name="REQUEST: Form-encoded POST is also supported",
                method="POST",
                user=self.admin_user,
                data={**model_params, "value": "David"},
                expected=ExpectedResult(response_validators=[
                    response_has_widget,
                    widget_has_input(name="value", value="David"),
                ]),
            ),
            RequestScenario(
                name="AUTH: User without model access is denied",
                method="POST",
                user=self.normal_user,
                content_type="application/json",
                data=model_params,
                expected=ExpectedResult(status_code=403),
            ),
            RequestScenario(
                name="AUTH: Anonymous request redirects to login",
                method="POST",
                content_type="application/json",
                data=model_params,
                expected=ExpectedResult(status_code=302),
            ),
            RequestScenario(
                name="REQUEST: GET is rejected",
                user=self.admin_user,
                query_params=model_params,
                expected=ExpectedResult(status_code=405),
            ),
        ]
        for name, data in [
            ("Missing scope", {key: value for key, value in model_params.items() if key != "scope"}),
            ("Missing scope ID", {key: value for key, value in model_params.items() if key != "id"}),
            ("Missing field path", {key: value for key, value in model_params.items() if key != "field_path"}),
            ("Missing lookup", {key: value for key, value in model_params.items() if key != "lookup_id"}),
            ("Unknown field", {**model_params, "field_path": "missing_field"}),
            ("Unknown lookup", {**model_params, "lookup_id": "missing_lookup"}),
            ("Lookup unavailable for field", {**model_params, "lookup_id": "foreign_advanced"}),
            ("Nested lookup has no value editor", {**model_params, "field_path": "country", "lookup_id": "foreign_advanced"}),
            ("JSON body must be an object", []),
            ("Malformed JSON", '{"scope":'),
        ]:
            scenarios.append(RequestScenario(
                name=f"INVALID: {name}",
                method="POST",
                user=self.admin_user,
                content_type="application/json",
                data=data,
                expected=ExpectedResult(status_code=400),
            ))
        return scenarios

    @skip("TODO: Grant model access but deny access to the requested field")
    def test_inaccessible_field_cannot_render_editor(self):
        """A direct request must not render an editor for a forbidden field."""

    @skip("TODO: Create a workspace dataview tile")
    def test_workspace_dataview_editor(self):
        """The tile-prefixed field uses its underlying application field's editor."""

    @skip("TODO: Create a Decimal analytics field without an application field")
    def test_workspace_analytics_editor(self):
        """The standalone Decimal form factory restores a decimal value."""

    @skip("TODO: Create an analytics field with a lookup lacking SQL support")
    def test_workspace_unsupported_lookup_is_rejected(self):
        """The editor rejects a lookup that cannot execute for the analytics field."""

    @skip("TODO: Define the structured-value restoration contract and widget fixture")
    def test_structured_value_restoration(self):
        """Objects and arrays restore without coercing their contents to strings."""

    def view_token(self) -> str:
        """Issue a test capability for one readable field on the dynamic customer model."""
        return PermissionToken(
            model_label=self.CustomerModel._meta.label_lower,
            audience=str(self.normal_user.pk), expiry=timezone.now() + timedelta(minutes=5),
            rule=AccessRule(
                row_permissions=[RowPolicyRuleContent(permissions=["view"], conditions=[])],
                field_permissions={"first_name": ["view"]},
            ),
        ).sign()

    def attach_view_token(self, scenario: RequestScenario) -> None:
        """Carry the signed grant in the URL, including when the request body is JSON."""
        scenario.query_params = {"_permission_token": self.view_token()}

    def test_filter_templates_forward_the_request_token(self) -> None:
        """Keep all filter subrequests scoped to the same capability as their parent view."""
        token = self.view_token()
        request = RequestFactory().get("/calendar/", {"_permission_token": token})
        request.user = self.normal_user
        content_type = self.get_content_type_for_model(self.CustomerModel)
        preference = UserListViewPreference.objects.create(user=self.normal_user, content_type=content_type)
        context = {"request": request, "scope": "model", "id": content_type.pk, "filter_host": preference}
        for name in ("container", "rendered"):
            with self.subTest(template=name), patch("bloomerp.middleware.current_request", return_value=request):
                html = render_to_string(f"cotton/features/filters/{name}.html", context)
                urls = re.findall(r'data-[a-z-]+-url="([^"]+)"', html)
                self.assertTrue(urls)
                for url in urls:
                    self.assertEqual(parse_qs(urlsplit(unescape(url)).query).get("_permission_token"), [token])
