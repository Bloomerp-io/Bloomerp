"""Owner-managed default-filter association scenarios."""
from django.contrib.contenttypes.models import ContentType

from bloomerp.filters.definition import Filter, FilterCondition
from bloomerp.models.filters.filter import SavedFilter
from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from bloomerp.models.workspaces.workspace import Workspace
from bloomerp.tests.base import (
    BloomerpComponentTestCase,
    ExpectedResult,
    RequestScenario,
)


class TestDefaultsComponent(BloomerpComponentTestCase):
    """Tests function `defaults` from `bloomerp/components/filters/defaults.py`."""

    view_name = 'components_filters_defaults'

    def extendedSetup(self):
        self.identifier = str(ContentType.objects.get_for_model(self.CustomerModel).pk)
        self.groups = [Filter(connector="AND", conditions=[
            FilterCondition(field_path="first_name", lookup_id="equals", value="David"),
        ]).model_dump(mode="json")]
        self.changed_groups = [Filter(connector="AND", conditions=[
            FilterCondition(field_path="first_name", lookup_id="equals", value="Emma"),
        ]).model_dump(mode="json")]
        self.preference = UserListViewPreference.objects.create(
            user=self.admin_user,
            content_type_id=self.identifier,
        )
        self.workspace = Workspace.objects.create(
            user=self.admin_user,
            name="Default-filter workspace",
        )
        self.model_filter = SavedFilter.objects.create(
            scope="model", identifier=self.identifier, name="Existing model filter",
            filters=self.groups,
        )
        self.workspace_filter = SavedFilter.objects.create(
            scope="workspace", identifier=str(self.workspace.pk), name="Existing workspace filter",
            filters=[],
        )
        self.preference.add_default_filter(self.model_filter)

    def payload(self, host, scope, **params):
        return {"scope": scope, "host_id": str(host.pk), **params}

    def exact_filter(self, record):
        expected = {
            "id": str(record.pk),
            "name": record.name,
            "scope": record.scope,
            "identifier": record.identifier,
            "filters": record.filters,
        }
        return self._named_validator(
            f"exact_filter({record.pk})",
            lambda response: response.json() == expected,
        )

    def attached_to(self, host):
        def validate(response):
            return host.default_filters.filter(pk=response.json()["id"]).exists()

        return self._named_validator("returned_filter_is_a_default", validate)

    def creates_new_filter_without_changing(self, original):
        def validate(response):
            created = SavedFilter.objects.get(pk=response.json()["id"])
            return (
                created.pk != original.pk
                and created.filters == self.changed_groups
                and SavedFilter.objects.get(pk=original.pk).filters == self.groups
            )

        return self._named_validator("creates_new_filter_without_changing_existing", validate)

    def get_test_scenarios(self) -> list[RequestScenario]:
        return [
            RequestScenario(
                name="ADD: Reuses a matching saved model filter",
                method="POST",
                user=self.admin_user,
                content_type="application/json",
                data=self.payload(
                    self.preference, "model", action="add",
                    filter_id=str(self.model_filter.pk), filters=self.groups,
                ),
                expected=ExpectedResult(response_validators=[
                    self.exact_filter(self.model_filter), self.attached_to(self.preference),
                ]),
            ),
            RequestScenario(
                name="ADD: Creates and associates a filter when no saved filter is selected",
                method="POST",
                user=self.admin_user,
                content_type="application/json",
                data=self.payload(self.preference, "model", action="add", filters=self.groups),
                expected=ExpectedResult(response_validators=[
                    self.contains_text('"name": "Filter 1"'), self.attached_to(self.preference),
                ]),
            ),
            RequestScenario(
                name="ADD: Changed conditions create a filter without overwriting the selected preset",
                method="POST",
                user=self.admin_user,
                content_type="application/json",
                data=self.payload(
                    self.preference, "model", action="add",
                    filter_id=str(self.model_filter.pk), filters=self.changed_groups,
                ),
                expected=ExpectedResult(response_validators=[
                    self.attached_to(self.preference),
                    self.creates_new_filter_without_changing(self.model_filter),
                ]),
            ),
            RequestScenario(
                name="REMOVE: Removes only the default association",
                method="POST",
                user=self.admin_user,
                content_type="application/json",
                data=self.payload(
                    self.preference, "model", action="remove", filter_id=str(self.model_filter.pk),
                ),
                expected=ExpectedResult(response_validators=[
                    self.exact_filter(self.model_filter),
                    self._named_validator(
                        "saved_filter_remains_unassociated",
                        lambda response: (
                            SavedFilter.objects.filter(pk=self.model_filter.pk).exists()
                            and not self.preference.default_filters.filter(pk=self.model_filter.pk).exists()
                        ),
                    ),
                ]),
            ),
            RequestScenario(
                name="AUTH: A non-owner cannot change workspace defaults",
                method="POST",
                user=self.normal_user,
                content_type="application/json",
                data=self.payload(
                    self.workspace, "workspace", action="add", filters=[],
                ),
                expected=ExpectedResult(status_code=403),
            ),
            RequestScenario(
                name="AUTH: Anonymous requests redirect to login",
                method="POST",
                content_type="application/json",
                data=self.payload(self.preference, "model", action="add", filters=self.groups),
                expected=ExpectedResult(status_code=302),
            ),
            RequestScenario(
                name="REQUEST: GET is rejected",
                user=self.admin_user,
                query_params=self.payload(self.preference, "model", action="add", filters=self.groups),
                expected=ExpectedResult(status_code=405),
            ),
            *[
                RequestScenario(
                    name=f"INVALID: {name}",
                    method="POST",
                    user=self.admin_user,
                    content_type="application/json",
                    data=data,
                    expected=ExpectedResult(status_code=status),
                )
                for name, data, status in [
                    ("Unknown host scope", {"scope": "unknown", "host_id": str(self.preference.pk), "action": "add"}, 400),
                    ("Unknown action", self.payload(self.preference, "model", action="replace"), 400),
                    ("Unassociated filter cannot be removed", self.payload(self.preference, "model", action="remove", filter_id=str(self.workspace_filter.pk)), 404),
                    ("Malformed filter groups are rejected", self.payload(self.preference, "model", action="add", filters={}), 400),
                ]
            ],
        ]
