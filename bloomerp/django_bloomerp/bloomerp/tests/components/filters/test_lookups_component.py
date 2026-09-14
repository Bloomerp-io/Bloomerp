"""Lookup discovery scenarios; policy and workspace fixtures remain placeholders."""
from unittest import skip

from bloomerp.tests.base import (
    BloomerpComponentTestCase,
    ExpectedResult,
    RequestScenario,
)

from .validators import (
    response_contains_lookup,
    response_excludes_lookup,
    response_has_lookup_metadata,
    response_is_empty,
    response_is_list,
)


class TestLookupsComponent(BloomerpComponentTestCase):
    """Discover lookups by field type or a scoped model field path."""

    view_name = "components_filters_lookups"
    create_foreign_models = True

    def get_test_scenarios(self) -> list[RequestScenario]:
        model_params = {
            "scope": "model",
            "id": self.get_content_type_for_model(self.CustomerModel).pk,
            "field_path": "first_name",
        }
        return [
            RequestScenario(
                name="TYPE: CharField exposes terminal text lookups",
                user=self.admin_user,
                query_params={"field_type": "CharField"},
                expected=ExpectedResult(response_validators=[
                    response_has_lookup_metadata,
                    response_contains_lookup("equals", nested=False),
                    response_contains_lookup("contains", nested=False),
                    response_excludes_lookup("foreign_advanced"),
                ]),
            ),
            RequestScenario(
                name="TYPE: Metadata discovery does not require model access",
                user=self.normal_user,
                query_params={"field_type": "CharField"},
                expected=ExpectedResult(response_validators=[
                    response_has_lookup_metadata,
                    response_contains_lookup("contains", nested=False),
                ]),
            ),
            RequestScenario(
                name="TYPE: Field type without lookups returns an empty list",
                user=self.admin_user,
                query_params={"field_type": "CodeField"},
                expected=ExpectedResult(response_validators=[response_is_list, response_is_empty]),
            ),
            RequestScenario(
                name="MODEL: Text field exposes text lookups",
                user=self.admin_user,
                query_params=model_params,
                expected=ExpectedResult(response_validators=[
                    response_has_lookup_metadata,
                    response_contains_lookup("contains", nested=False),
                ]),
            ),
            RequestScenario(
                name="MODEL: Numeric field exposes numeric lookups",
                user=self.admin_user,
                query_params={**model_params, "field_path": "age"},
                expected=ExpectedResult(response_validators=[
                    response_has_lookup_metadata,
                    response_contains_lookup("greater_than", nested=False),
                    response_excludes_lookup("contains"),
                ]),
            ),
            RequestScenario(
                name="MODEL: Foreign field exposes its nested lookup",
                user=self.admin_user,
                query_params={**model_params, "field_path": "country"},
                expected=ExpectedResult(response_validators=[
                    response_has_lookup_metadata,
                    response_contains_lookup("foreign_advanced", nested=True),
                ]),
            ),
            RequestScenario(
                name="NESTED: Related text field uses its own lookups",
                user=self.admin_user,
                query_params={**model_params, "field_path": "country__name"},
                expected=ExpectedResult(response_validators=[
                    response_has_lookup_metadata,
                    response_contains_lookup("contains", nested=False),
                    response_excludes_lookup("foreign_advanced"),
                ]),
            ),
            RequestScenario(
                name="MODEL: User without model access is denied",
                user=self.normal_user,
                query_params=model_params,
                expected=ExpectedResult(status_code=403),
            ),
            RequestScenario(
                name="AUTH: Anonymous metadata request redirects to login",
                query_params={"field_type": "CharField"},
                expected=ExpectedResult(status_code=302),
            ),
            *[
                RequestScenario(
                    name=f"INVALID: {name}",
                    user=self.admin_user,
                    query_params=params,
                    expected=ExpectedResult(status_code=400),
                )
                for name, params in [
                    ("Missing field type and scope", {}),
                    ("Unknown field type", {"field_type": "MissingFieldType"}),
                    ("Invalid scope", {**model_params, "scope": "unknown"}),
                    ("Missing scope ID", {"scope": "model", "field_path": "first_name"}),
                    ("Missing field path", {"scope": "model", "id": model_params["id"]}),
                    ("Unknown field path", {**model_params, "field_path": "missing_field"}),
                ]
            ],
        ]

    @skip("TODO: Grant model access but deny the requested field in its field policy")
    def test_inaccessible_field_does_not_expose_lookups(self):
        """A direct scoped request cannot discover lookups for a forbidden field."""

    @skip("TODO: Add a JSON field to the model fixtures")
    def test_json_key_lookups(self):
        """A JSON key exposes terminal JSON lookups and further key navigation."""

    @skip("TODO: Create a workspace dataview tile")
    def test_workspace_dataview_lookups(self):
        """A tile-prefixed field exposes the underlying model field's lookups."""

    @skip("TODO: Create an analytics field with both SQL-supported and unsupported lookups")
    def test_workspace_analytics_filters_out_unsupported_lookups(self):
        """Only SQL-supported terminal lookups and nested lookups are returned."""

    @skip("TODO: Create a workspace inaccessible to normal_user")
    def test_workspace_access_denied(self):
        """Direct lookup discovery for an inaccessible workspace returns 403."""
