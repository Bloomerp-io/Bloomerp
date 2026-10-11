"""Keep embedded search preferences scoped, authorized, and independent of selection."""

import re
import time
from html import unescape
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.contrib.contenttypes.models import ContentType
from django.http import HttpResponse
from django.test import RequestFactory
from django.urls import reverse

from bloomerp.components.objects.dataviews.dataview import (
    DATAVIEW_OPERATION_CONTEXT_MAX_AGE,
    DATAVIEW_OPERATION_CONTEXT_PARAM,
    _sign_dataview_operation_context,
    dataview,
)
from bloomerp.filters.definition import Filter, FilterCondition
from bloomerp.models.application_field import ApplicationField
from bloomerp.models.filters.filter import SavedFilter
from bloomerp.models.project_management.todo import Todo, TodoStatus
from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from bloomerp.permissions.definition import (
    AccessRule,
    BloomerpPermission,
    RowPolicyRuleContent,
)
from bloomerp.permissions.manager import PolicyManager
from bloomerp.services.preference_services import PreferenceManager
from bloomerp.tests.base import (
    BloomerpComponentTestCase,
    ExpectedResult,
    RequestScenario,
)
from bloomerp.workspaces.dataview_tile.model import DataViewTileConfig
from bloomerp.workspaces.dataview_tile.render import DataViewTileRenderer

PREFERENCE_PARAM = "_dataview_preference_id"


class TestDataviewSearchPreferenceComponent(BloomerpComponentTestCase):
    """Exercise explicit shell preference context through real routed requests."""

    view_name = "components_dataview"
    auto_create_customers = False

    def prepare_embedding(
        self, scenario: RequestScenario, *, require_emitted_context: bool = True
    ) -> None:
        """Create a scoped embedded table that differs from the selected Kanban."""
        self.content_type = ContentType.objects.get_for_model(Todo)
        self.selected = PreferenceManager(self.admin_user).get_or_create_selected(
            UserListViewPreference, {"content_type_id": self.content_type.pk}
        )
        self.selected.view_type = "kanban"
        self.selected.options = {"kanban": {"group_by_field": "status"}}
        self.selected.save(update_fields=["view_type", "options"])
        PreferenceManager(self.normal_user).get_or_create_selected(
            UserListViewPreference, {"content_type_id": self.content_type.pk}
        )
        title_field = ApplicationField.get_for_model(Todo).get(field="title")
        self.embedded = UserListViewPreference.objects.create(
            user=self.normal_user,
            content_type=self.content_type,
            selected=False,
            name="Workspace table",
            view_type="table",
            display_fields={"table": [title_field.pk]},
        )
        saved_filter = SavedFilter.objects.create(
            name="Workspace incomplete tasks",
            scope="model",
            identifier=str(self.content_type.pk),
            filters=[
                Filter(
                    connector="AND",
                    conditions=[
                        FilterCondition(
                            field_path="status",
                            lookup_id="equals",
                            value=TodoStatus.IN_PROGRESS,
                        )
                    ],
                ).model_dump(mode="json")
            ],
        )
        self.embedded.add_default_filter(saved_filter)
        self.alpha = Todo.objects.create(
            title="Search Alpha", status=TodoStatus.IN_PROGRESS
        )
        self.beta = Todo.objects.create(
            title="Search Beta", status=TodoStatus.IN_PROGRESS
        )
        self.excluded = Todo.objects.create(
            title="Search Alpha hidden", status=TodoStatus.COMPLETED
        )
        request = RequestFactory().get("/", {"_component_id": "workspace-table"})
        original_query = request.GET.copy()
        request.user = self.admin_user
        self.token = _sign_dataview_operation_context(request, self.embedded)
        self.embedding_html = dataview(
            request,
            self.content_type.pk,
            preference=self.embedded,
        ).content.decode()
        self.assertEqual(request.GET, original_query)
        embedded_url_match = re.search(r'data-url="([^"]+)"', self.embedding_html)
        self.assertIsNotNone(embedded_url_match)
        embedded_params = parse_qs(
            urlsplit(unescape(embedded_url_match.group(1))).query
        )
        if require_emitted_context:
            self.assertEqual(embedded_params[PREFERENCE_PARAM], [str(self.embedded.pk)])
            self.assertTrue(embedded_params[DATAVIEW_OPERATION_CONTEXT_PARAM])
            self.token = embedded_params[DATAVIEW_OPERATION_CONTEXT_PARAM][0]
        self.assertEqual(embedded_params["_component_id"], ["workspace-table"])
        scenario.view_kwargs = {"content_type_id": self.content_type.pk}
        scenario.query_params = scenario.query_params or {}
        scenario.query_params.update(
            {
                PREFERENCE_PARAM: str(self.embedded.pk),
                DATAVIEW_OPERATION_CONTEXT_PARAM: self.token,
            }
        )

    def prepare_two_tiles(self, scenario: RequestScenario) -> None:
        """Render two real same-model tiles with different preferences and filters."""
        self.prepare_embedding(scenario, require_emitted_context=False)
        title_field = ApplicationField.get_for_model(Todo).get(field="title")
        self.board = UserListViewPreference.objects.create(
            user=self.normal_user,
            content_type=self.content_type,
            selected=False,
            name="Other workspace board",
            view_type="kanban",
            display_fields={"kanban": [title_field.pk]},
            options={"kanban": {"group_by_field": "status"}},
        )
        request = RequestFactory().get(
            "/",
            {
                "tile_id": "first-tile",
                "workspace_id": "test-workspace",
                "max_cols": "2",
            },
        )
        request.user = self.admin_user
        original_query = request.GET.copy()
        self.tile_urls = []
        for preference, initial in (
            (self.embedded, {"title": self.alpha.title}),
            (self.board, {"status": TodoStatus.COMPLETED}),
        ):
            markup = DataViewTileRenderer.render(
                DataViewTileConfig(
                    content_type_id=self.content_type.pk,
                    list_view_preference_id=preference.pk,
                    initial_query_params=initial,
                    actions=[],
                ),
                request,
            )
            url_match = re.search(r'data-url="([^"]+)"', markup)
            self.assertIsNotNone(url_match)
            url = unescape(url_match.group(1))
            params = parse_qs(urlsplit(url).query)
            for key, value in initial.items():
                self.assertEqual(params[key], [str(value)])
            for key in original_query:
                self.assertNotIn(key, params)
            self.assertEqual(request.GET, original_query)
            self.tile_urls.append(url)
        scenario.query_params = parse_qs(urlsplit(self.tile_urls[0]).query)
        scenario.query_params["q"] = "Search"

    def isolates_two_rendered_tiles(self, response: HttpResponse) -> bool:
        """Search and clear emitted tile URLs without mixing their preferences."""
        self.assertEqual(response.context["preference"].pk, self.embedded.pk)
        self.assertEqual(response.context["preference"].view_type, "table")
        self.assertTrue(self.renders_embedded_search(response))
        for index, preference, expected_ids, retained_key in (
            (1, self.board, {self.excluded.pk}, "status"),
            (0, self.embedded, {self.alpha.pk}, "title"),
        ):
            params = parse_qs(urlsplit(self.tile_urls[index]).query)
            original_token = params[DATAVIEW_OPERATION_CONTEXT_PARAM]
            for query in ("Alpha", ""):
                params["q"] = query
                with patch(
                    "django.core.signing.time.time", return_value=time.time() + 60
                ):
                    current = self.client.get(
                        reverse(
                            self.view_name,
                            kwargs={
                                "content_type_id": self.content_type.pk,
                            },
                        ),
                        data=params,
                    )
                self.assertEqual(current.status_code, 200)
                self.assertEqual(current.context["preference"].pk, preference.pk)
                self.assertEqual(
                    current.context["preference"].view_type, preference.view_type
                )
                self.assertEqual(
                    {entry.pk for entry in current.context["queryset"]}, expected_ids
                )
                next_params = parse_qs(urlsplit(current.context["data_view_url"]).query)
                self.assertEqual(next_params[retained_key], params[retained_key])
                self.assertEqual(
                    next_params[DATAVIEW_OPERATION_CONTEXT_PARAM], original_token
                )
                params = next_params
        return self.selected_is_unchanged(response)

    def prepare_embedded_bulk_dialog(self, scenario: RequestScenario) -> None:
        """Forward the same embedded data URL parameters used by bulk-action UI."""
        self.prepare_embedding(scenario)
        url_match = re.search(r'data-url="([^"]+)"', self.embedding_html)
        self.assertIsNotNone(url_match)
        scenario.query_params = parse_qs(urlsplit(unescape(url_match.group(1))).query)
        scenario.query_params.update(
            {
                "selection": "selected",
                "object_ids": str(self.alpha.pk),
                "q": "Alpha",
            }
        )

    def renders_bulk_dialog_without_mutation(self, response: HttpResponse) -> bool:
        """Render exactly the selected record without consuming transport as filters."""
        return (
            "Delete 1 object(s)" in response.content.decode()
            and Todo.objects.filter(
                pk__in=[self.alpha.pk, self.beta.pk, self.excluded.pk]
            ).count()
            == 3
            and self.selected_is_unchanged(response)
        )

    def prepare_private(self, scenario: RequestScenario) -> None:
        """Request another user's private preference without embedding authority."""
        self.prepare_embedding(scenario)
        scenario.query_params.pop(DATAVIEW_OPERATION_CONTEXT_PARAM)

    def prepare_owned(self, scenario: RequestScenario) -> None:
        """Use an owned, nonselected preference without requiring a signature."""
        self.prepare_private(scenario)
        self.embedded.user = self.admin_user
        self.embedded.save(update_fields=["user"])

    def prepare_missing_id(self, scenario: RequestScenario) -> None:
        """Reject a well-formed ID that does not identify an existing preference."""
        self.prepare_embedding(scenario)
        scenario.query_params[PREFERENCE_PARAM] = "2147483647"

    def prepare_forged(self, scenario: RequestScenario) -> None:
        """Corrupt an otherwise correctly scoped embedding signature."""
        self.prepare_embedding(scenario)
        scenario.query_params[DATAVIEW_OPERATION_CONTEXT_PARAM] = self.token + "forged"

    def prepare_expired(self, scenario: RequestScenario) -> None:
        """Reject embedding authority that has outlived its validity window."""
        self.prepare_embedding(scenario)
        request = RequestFactory().get("/")
        request.user = self.admin_user
        expired_time = time.time() - DATAVIEW_OPERATION_CONTEXT_MAX_AGE - 60
        with patch("django.core.signing.time.time", return_value=expired_time):
            scenario.query_params[DATAVIEW_OPERATION_CONTEXT_PARAM] = (
                _sign_dataview_operation_context(request, self.embedded)
            )

    def prepare_deleted(self, scenario: RequestScenario) -> None:
        """Reject a valid signed context when its preference has been deleted."""
        self.prepare_embedding(scenario)
        deleted = UserListViewPreference.objects.create(
            user=self.normal_user,
            content_type=self.content_type,
            selected=False,
        )
        request = RequestFactory().get("/")
        request.user = self.admin_user
        scenario.query_params[PREFERENCE_PARAM] = str(deleted.pk)
        scenario.query_params[DATAVIEW_OPERATION_CONTEXT_PARAM] = (
            _sign_dataview_operation_context(request, deleted)
        )
        deleted.delete()

    def prepare_cross_user(self, scenario: RequestScenario) -> None:
        """Supply a token issued for a different user to the current requester."""
        self.prepare_embedding(scenario)
        request = RequestFactory().get("/")
        request.user = self.normal_user
        scenario.query_params[DATAVIEW_OPERATION_CONTEXT_PARAM] = (
            _sign_dataview_operation_context(request, self.embedded)
        )

    def prepare_cross_content_type(self, scenario: RequestScenario) -> None:
        """Try using a signed Todo preference against a different model route."""
        self.prepare_embedding(scenario)
        scenario.view_kwargs["content_type_id"] = ContentType.objects.get_for_model(
            SavedFilter
        ).pk

    def prepare_cross_preference(self, scenario: RequestScenario) -> None:
        """Try using a legitimate signature to read a different private preference."""
        self.prepare_embedding(scenario)
        other = UserListViewPreference.objects.create(
            user=self.normal_user,
            content_type=self.content_type,
            selected=False,
        )
        scenario.query_params[PREFERENCE_PARAM] = str(other.pk)

    def prepare_invalid_id(self, scenario: RequestScenario) -> None:
        """Supply a malformed preference ID rather than silently falling back."""
        self.prepare_embedding(scenario)
        scenario.query_params[PREFERENCE_PARAM] = "not-an-id"

    def prepare_shared(self, scenario: RequestScenario) -> None:
        """Make the explicit preference available by direct share without a token."""
        self.prepare_private(scenario)
        self.embedded.shared_with_users.add(self.admin_user)

    def prepare_shared_reference(self, scenario: RequestScenario) -> None:
        """Resolve a user's available reference to its live shared source."""
        self.prepare_shared(scenario)
        reference = UserListViewPreference.objects.create(
            user=self.admin_user,
            content_type=self.content_type,
            source_object=self.embedded,
            selected=False,
        )
        scenario.query_params[PREFERENCE_PARAM] = str(reference.pk)

    def prepare_restricted_user(self, scenario: RequestScenario) -> None:
        """Grant embedding access without granting extra row or field access."""
        self.prepare_embedding(scenario)
        self.embedded.user = self.admin_user
        content_field = ApplicationField.get_for_model(Todo).get(field="content")
        self.embedded.display_fields["table"].append(content_field.pk)
        self.embedded.save(update_fields=["user", "display_fields"])
        self.alpha.content = "Confidential embedded content"
        self.alpha.save(update_fields=["content"])
        PolicyManager.create_policy(
            Todo,
            access_rule=AccessRule(
                row_permissions=[
                    RowPolicyRuleContent(
                        permissions=[BloomerpPermission.VIEW],
                        conditions=[
                            FilterCondition(
                                field_path="title",
                                lookup_id="equals",
                                value=self.alpha.title,
                            )
                        ],
                    )
                ],
                field_permissions={
                    "title": [BloomerpPermission.VIEW],
                    "status": [BloomerpPermission.VIEW],
                },
            ),
            global_permissions=[BloomerpPermission.VIEW],
        ).assign_user(self.normal_user)
        request = RequestFactory().get("/")
        request.user = self.normal_user
        scenario.query_params[DATAVIEW_OPERATION_CONTEXT_PARAM] = (
            _sign_dataview_operation_context(request, self.embedded)
        )

    def respects_row_and_field_permissions(self, response: HttpResponse) -> bool:
        """Require a signed embedding to retain the requester's row and field limits."""
        return (
            self.renders_embedded_search(response)
            and "Confidential embedded content" not in response.content.decode()
            and {field.field for field in response.context["dataview_render_fields"]}
            == {"title"}
        )

    def prepare_normal(self, scenario: RequestScenario) -> None:
        """Leave the ordinary shell free to use the user's selected preference."""
        self.prepare_embedding(scenario)
        scenario.query_params.pop(PREFERENCE_PARAM)
        scenario.query_params.pop(DATAVIEW_OPERATION_CONTEXT_PARAM)

    def selected_is_unchanged(self, response: HttpResponse) -> bool:
        """Ensure a search never writes the globally selected list preference."""
        self.selected.refresh_from_db()
        self.embedded.refresh_from_db()
        return (
            self.selected.selected
            and not self.embedded.selected
            and self.selected.view_type == "kanban"
        )

    def renders_embedded_search(self, response: HttpResponse) -> bool:
        """Check the actual renderer, explicit fields, filtered rows, and selection."""
        preference = response.context["preference"]
        return (
            preference.pk == self.embedded.pk
            and preference.view_type == "table"
            and preference.display_fields == self.embedded.display_fields
            and {entry.pk for entry in response.context["queryset"]} == {self.alpha.pk}
            and 'data-view-type="table"' in response.content.decode()
            and self.selected_is_unchanged(response)
        )

    def retains_context_after_search_and_clear(self, response: HttpResponse) -> bool:
        """Reuse server-emitted shell URLs for another query and a cleared query."""
        if not self.renders_embedded_search(response):
            return False
        for query, expected_ids in (
            ("Beta", {self.beta.pk}),
            ("", {self.alpha.pk, self.beta.pk}),
            ("Alpha", {self.alpha.pk}),
        ):
            params = parse_qs(urlsplit(response.context["data_view_url"]).query)
            self.assertEqual(params[PREFERENCE_PARAM], [str(self.embedded.pk)])
            self.assertTrue(params[DATAVIEW_OPERATION_CONTEXT_PARAM])
            params["q"] = query
            response = self.client.get(
                reverse(
                    self.view_name,
                    kwargs={
                        "content_type_id": self.content_type.pk,
                    },
                ),
                data=params,
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context["preference"].pk, self.embedded.pk)
            self.assertEqual(
                {entry.pk for entry in response.context["queryset"]}, expected_ids
            )
        return self.selected_is_unchanged(response)

    def renders_embedded_fragment(self, response: HttpResponse) -> bool:
        """Keep the explicit table and filtered rows in an HTMX data-only swap."""
        markup = response.content.decode()
        return (
            response.context["is_data_section_request"]
            and response.context["preference"].pk == self.embedded.pk
            and response.context["preference"].view_type == "table"
            and {entry.pk for entry in response.context["queryset"]} == {self.alpha.pk}
            and "<table" in markup
            and 'data-view-type="table"' not in markup
            and self.selected_is_unchanged(response)
        )

    def renders_normal_selection(self, response: HttpResponse) -> bool:
        """Confirm ordinary model lists retain their independently selected renderer."""
        return (
            response.context["preference"].pk == self.selected.pk
            and 'data-view-type="kanban"' in response.content.decode()
            and PREFERENCE_PARAM not in response.context["data_view_url"]
            and DATAVIEW_OPERATION_CONTEXT_PARAM
            not in response.context["data_view_url"]
            and self.selected_is_unchanged(response)
        )

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Cover authorized reuse, security boundaries, and ordinary selection."""
        scenarios = [
            RequestScenario(
                name="Embedded transport parameters do not become bulk action filters",
                view_name="components_bulk_actions",
                user=self.admin_user,
                prepare=self.prepare_embedded_bulk_dialog,
                expected=ExpectedResult(
                    response_validators=self.renders_bulk_dialog_without_mutation
                ),
            ),
            RequestScenario(
                name="HTMX data-only search retains embedded table and filters",
                user=self.admin_user,
                prepare=self.prepare_embedding,
                query_params={"q": "Alpha"},
                headers={"HX-Target": "data-view-data-section", "HX-Request": "true"},
                expected=ExpectedResult(
                    response_validators=self.renders_embedded_fragment
                ),
            ),
            RequestScenario(
                name="Real same-model tiles preserve independent preferences and initial filters",
                user=self.admin_user,
                prepare=self.prepare_two_tiles,
                expected=ExpectedResult(
                    response_validators=self.isolates_two_rendered_tiles
                ),
            ),
            RequestScenario(
                name="Signed embedding preserves normal-user row and field permissions",
                user=self.normal_user,
                prepare=self.prepare_restricted_user,
                query_params={"q": "Search"},
                expected=ExpectedResult(
                    response_validators=self.respects_row_and_field_permissions
                ),
            ),
            RequestScenario(
                name="Embedded search survives repeated searches and clearing",
                user=self.admin_user,
                prepare=self.prepare_embedding,
                query_params={"q": "Alpha"},
                expected=ExpectedResult(
                    response_validators=self.retains_context_after_search_and_clear
                ),
            ),
            RequestScenario(
                name="Ordinary model search keeps the globally selected renderer",
                user=self.admin_user,
                prepare=self.prepare_normal,
                query_params={"q": "Alpha"},
                expected=ExpectedResult(
                    response_validators=self.renders_normal_selection
                ),
            ),
        ]
        for name, prepare in (
            (
                "Owned nonselected preference is available without a signature",
                self.prepare_owned,
            ),
            (
                "Shared preference is available without a signed context",
                self.prepare_shared,
            ),
            (
                "Shared reference resolves its effective preference",
                self.prepare_shared_reference,
            ),
        ):
            scenarios.append(
                RequestScenario(
                    name=name,
                    user=self.admin_user,
                    prepare=prepare,
                    query_params={"q": "Alpha"},
                    expected=ExpectedResult(
                        response_validators=self.renders_embedded_search
                    ),
                )
            )
        for name, prepare in (
            ("Private preference ID alone cannot grant access", self.prepare_private),
            ("Forged embedding token is rejected", self.prepare_forged),
            ("Expired embedding token is rejected", self.prepare_expired),
            ("Deleted signed preference is rejected", self.prepare_deleted),
            ("Embedding token cannot cross users", self.prepare_cross_user),
            (
                "Embedding token cannot cross content types",
                self.prepare_cross_content_type,
            ),
            ("Embedding token cannot cross preferences", self.prepare_cross_preference),
            ("Malformed preference ID is rejected", self.prepare_invalid_id),
            ("Missing preference ID is rejected", self.prepare_missing_id),
        ):
            scenarios.append(
                RequestScenario(
                    name=name,
                    user=self.admin_user,
                    prepare=prepare,
                    query_params={"q": "Alpha"},
                    expected=ExpectedResult(
                        status_code=404, response_validators=self.selected_is_unchanged
                    ),
                )
            )
        return scenarios
