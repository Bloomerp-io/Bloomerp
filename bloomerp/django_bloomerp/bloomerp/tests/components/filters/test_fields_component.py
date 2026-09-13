"""Field discovery scenarios; workspace fixtures remain explicit placeholders."""
import json
from unittest import skip

from django.http import HttpResponse

from bloomerp.tests.base import (
    BloomerpComponentTestCase,
    ExpectedResult,
    RequestScenario,
)

from .validators import response_is_list


def response_has_field_contexts(resp: HttpResponse) -> bool:
    groups = json.loads(resp.content)
    return bool(groups) and all(
        isinstance(group.get("name"), str)
        and bool(group.get("fields"))
        and all(
            isinstance(field.get("field"), str)
            and isinstance(field.get("label"), str)
            and set(field.get("context", {})) == {"field_type", "application_field"}
            and isinstance(field["context"]["field_type"], str)
            and isinstance(field["context"]["application_field"], int)
            for field in group["fields"]
        )
        for group in groups
    )


def response_contains_field(name: str):
    def contains_field(resp: HttpResponse) -> bool:
        return any(
            field["field"] == name
            for group in json.loads(resp.content)
            for field in group["fields"]
        )

    contains_field.__name__ = f"response_contains_field({name!r})"
    return contains_field


class TestFieldsComponent(BloomerpComponentTestCase):
    """Discover model fields and nested children through the fields component."""

    view_name = "components_filters_fields"
    create_foreign_models = True

    def get_test_scenarios(self) -> list[RequestScenario]:
        model_params = {
            "scope": "model",
            "id": self.get_content_type_for_model(self.CustomerModel).pk,
        }
        nested_params = {
            **model_params,
            "field_path": "country",
            "lookup_id": "foreign_advanced",
        }

        scenarios = [
            RequestScenario(
                name="MODEL: Admin sees fields with serialized context IDs",
                user=self.admin_user,
                query_params=model_params,
                expected=ExpectedResult(response_validators=[
                    response_is_list,
                    response_has_field_contexts,
                    response_contains_field("first_name"),
                ]),
            ),
            RequestScenario(
                name="MODEL: User without model access is denied",
                user=self.normal_user,
                query_params=model_params,
                expected=ExpectedResult(status_code=403),
            ),
            RequestScenario(
                name="AUTH: Anonymous user is redirected to login",
                query_params=model_params,
                expected=ExpectedResult(status_code=302),
            ),
            RequestScenario(
                name="NESTED: Foreign lookup returns related model fields",
                user=self.admin_user,
                query_params=nested_params,
                expected=ExpectedResult(response_validators=[
                    response_has_field_contexts,
                    response_contains_field("name"),
                    response_contains_field("planet"),
                ]),
            ),
            RequestScenario(
                name="NESTED: Multiple relation levels can be traversed",
                user=self.admin_user,
                query_params={**nested_params, "field_path": "country__planet"},
                expected=ExpectedResult(response_validators=[
                    response_has_field_contexts,
                    response_contains_field("name"),
                ]),
            ),
        ]

        for name, params in [
            ("Missing scope", {"id": model_params["id"]}),
            ("Invalid scope", {**model_params, "scope": "unknown"}),
            ("Missing scope ID", {"scope": "model"}),
            ("Nested field without lookup", {**model_params, "field_path": "country"}),
            ("Nested lookup without field", {**model_params, "lookup_id": "foreign_advanced"}),
            ("Unknown field", {**nested_params, "field_path": "missing_field"}),
            ("Unknown lookup", {**nested_params, "lookup_id": "missing_lookup"}),
        ]:
            scenarios.append(RequestScenario(
                name=f"INVALID: {name}",
                user=self.admin_user,
                query_params=params,
                expected=ExpectedResult(status_code=400),
            ))
        return scenarios

    @skip("TODO: Grant model access with a field policy exposing only first_name")
    def test_model_field_policy_limits_discovery(self):
        """Only permitted fields are returned; an empty field grant returns []."""

    @skip("TODO: Grant Customer access but deny access to the related Country model")
    def test_nested_discovery_does_not_expose_inaccessible_related_fields(self):
        """A direct nested request must not reveal forbidden related fields."""

    @skip("TODO: Add a model with a JSON field to the discovery fixtures")
    def test_json_key_discovery(self):
        """JSON key lookup returns the key descriptor and supports deeper keys."""

    @skip("TODO: Create a workspace with two dataview tiles using the same model")
    def test_workspace_dataview_fields(self):
        """Fields retain application-field IDs and distinct tile-prefixed paths."""

    @skip("TODO: Create a workspace with a Decimal analytics filter")
    def test_workspace_analytics_fields(self):
        """Analytics fields expose the mapped type and null application_field."""

    @skip("TODO: Create a workspace inaccessible to normal_user")
    def test_workspace_access_denied(self):
        """Direct field discovery for an inaccessible workspace returns 403."""
