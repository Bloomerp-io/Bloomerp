"""Exercise analytics filtering through the tile-rendering HTTP endpoint."""
import json

from bs4 import BeautifulSoup
from django.contrib.contenttypes.models import ContentType
from django.http import HttpResponse

from bloomerp.filters.definition import Filter, FilterCondition
from bloomerp.models.application_field import ApplicationField
from bloomerp.models.filters.filter import SavedFilter
from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from bloomerp.models.workspaces.tile import Tile
from bloomerp.models.workspaces.workspace import Workspace
from bloomerp.tests.base import (
    BloomerpComponentTestCase,
    ExpectedResult,
    RequestScenario,
)
from bloomerp.workspaces.analytics_tile.model import (
    AnalyticsTileConfig,
    AnalyticsTileFilter,
    FieldConfig,
)
from bloomerp.workspaces.dataview_tile.model import DataViewTileConfig


class TestRenderLayoutItemComponent(BloomerpComponentTestCase):
    view_name = 'components_render_layout_item'
    auto_create_customers = False

    def extendedSetup(self):
        self.tiles = []
        # Execute a real SELECT with deterministic rows, without relying on
        # application data or mocking query compilation/execution.
        for name in ('Names A', 'Names B'):
            config = AnalyticsTileConfig(
                query="SELECT 'David' AS first_name UNION ALL SELECT 'Daniel' UNION ALL SELECT 'Emma'",
                type='TABLE',
                fields={'columns': [FieldConfig(name='first_name')]},
                filters=[AnalyticsTileFilter(field='first_name', type='text')],
            )
            self.tiles.append(Tile.objects.create(
                name=name, type='ANALYTICS_TILE', schema=config.model_dump(mode='json'),
            ))
        for name in ('David', 'Daniel', 'Emma'):
            self.CustomerModel.objects.create(first_name=name, last_name='Example', age=30)
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        first_name = ApplicationField.get_by_field(self.CustomerModel, 'first_name')
        preference = UserListViewPreference.objects.create(
            user=self.admin_user, content_type=content_type, view_type='table',
            display_fields={'table': [first_name.pk]},
        )
        config = DataViewTileConfig(content_type_id=content_type.pk, list_view_preference_id=preference.pk, actions=[])
        self.dataview_tile = Tile.objects.create(name='Dataview names', type='DATAVIEW_TILE', schema=config.model_dump(mode='json'))
        self.workspace = Workspace.objects.create(
            name='Filter tests', user=self.admin_user,
            layout={'rows': [{'columns': 2, 'items': [{'id': str(tile.pk), 'colspan': 1} for tile in [*self.tiles, self.dataview_tile]]}]},
        )
        self.workspace_content_type = ContentType.objects.get_for_model(Workspace)

    def condition(self, value, path='first_name'):
        return FilterCondition(field_path=path, lookup_id='equals', value=value)

    def rendered_names(self, expected):
        def validate(response):
            soup = BeautifulSoup(response.content, 'html.parser')
            # Rendering errors are returned inside a 200 response: assert the
            # table exists, so an error cannot pass an empty-results tile_scenario.
            self.assertIsNotNone(soup.find('table'), response.content.decode())
            self.assertCountEqual([text for cell in soup.select('tbody td') if (text := cell.get_text(strip=True))], expected)
            return True
        return self._named_validator(f'rendered_first_names({expected!r})', validate)

    def tile_scenario(self, name, expected, *, groups=None, params=None, tile=None, defaults=False):
        query = {
            'tile_id': str((tile or self.tiles[0]).pk),
            'workspace_id': str(self.workspace.pk),
            'colspan': '1', 'max_cols': '2',
            **(params or {}),
        }
        if groups is not None:
            query['filter'] = json.dumps([group.model_dump() for group in groups])
        return RequestScenario(
            name=name,
            description=f'UC: {name}\nExpected Result: Rendered first_name cells are {expected!r}.',
            user=self.admin_user,
            prepare=self.prepare_default_filter if defaults else None,
            view_kwargs={'content_type_id': self.workspace_content_type.pk},
            query_params=query,
            expected=ExpectedResult(response_validators=self.rendered_names(expected)),
        )

    def prepare_default_filter(self, scenario):
        record = SavedFilter.objects.create(
            name='Default names', scope='workspace', identifier=str(self.workspace.pk),
            filters=[Filter(connector='AND', conditions=[self.condition('David', 'shared:first_name')]).model_dump()],
        )
        self.workspace.add_default_filter(record)

    def get_test_scenarios(self):
        shared = [Filter(connector='AND', conditions=[self.condition('David', 'shared:first_name')])]
        return [
            self.tile_scenario('Workspace defaults filter analytics tiles', ['David'], defaults=True),
            self.tile_scenario('Workspace defaults filter dataview tiles', ['David'], defaults=True, tile=self.dataview_tile),
            self.tile_scenario('Explicit empty filters override workspace defaults', ['David', 'Daniel', 'Emma'], defaults=True, groups=[]),
            self.tile_scenario('No filters renders all names', ['David', 'Daniel', 'Emma']),
            self.tile_scenario('Shorthand first_name filters the rendered tile', ['David'], params={'first_name': 'David'}),
            self.tile_scenario('Canonical first_name filters the rendered tile', ['David'], groups=[
                Filter(connector='AND', conditions=[self.condition('David')]),
            ]),
            self.tile_scenario('OR permits either first_name', ['David', 'Daniel'], groups=[
                Filter(connector='OR', conditions=[self.condition('David'), self.condition('Daniel')]),
            ]),
            self.tile_scenario('AND between groups narrows the alternatives', ['David'], groups=[
                Filter(connector='OR', conditions=[self.condition('David'), self.condition('Daniel')]),
                Filter(connector='AND', conditions=[self.condition('David')]),
            ]),
            self.tile_scenario('An unmatched first_name renders an empty table', [], groups=[
                Filter(connector='AND', conditions=[self.condition('Missing')]),
            ]),
            self.tile_scenario('Shared first_name filters the first tile', ['David'], groups=shared),
            self.tile_scenario('The same shared first_name filters the second tile', ['David'], groups=shared, tile=self.tiles[1]),
            self.tile_scenario('A condition for another tile leaves this tile unchanged', ['David', 'Daniel', 'Emma'], groups=[
                Filter(connector='AND', conditions=[self.condition('David', f'tile_{self.tiles[1].pk}:first_name')]),
            ]),
            self.tile_scenario('Quotes in first_name remain a literal value', [], groups=[
                Filter(connector='AND', conditions=[self.condition("David' OR '1'='1")]),
            ]),
            self.tile_scenario('Shared first_name filters a dataview tile', ['David'], groups=shared, tile=self.dataview_tile),
            self.tile_scenario('Shared OR conditions filter dataview rows', ['David', 'Daniel'], tile=self.dataview_tile, groups=[
                Filter(connector='OR', conditions=[self.condition('David', 'shared:first_name'), self.condition('Daniel', 'shared:first_name')]),
            ]),
            self.tile_scenario('Analytics-only conditions leave dataview rows unchanged', ['David', 'Daniel', 'Emma'], tile=self.dataview_tile, groups=[
                Filter(connector='AND', conditions=[self.condition('David', f'tile_{self.tiles[0].pk}:first_name')]),
            ]),
            self.tile_scenario('Clearing dataview filters restores all rows', ['David', 'Daniel', 'Emma'], tile=self.dataview_tile, groups=[]),
            self.tile_scenario('Clearing filters restores all names', ['David', 'Daniel', 'Emma'], groups=[]),
        ]


class TestRenderFieldSettingsComponent(BloomerpComponentTestCase):
    """Keep settings controls available before a newly added field is persisted."""

    view_name = "components_render_layout_item"
    auto_create_customers = False

    def setUp(self) -> None:
        """Prepare a create layout with one existing field and one available field."""
        from bloomerp.models import Todo
        from bloomerp.models.forms.form import Form

        super().setUp()
        self.status = ApplicationField.get_for_model(Todo).get(field="status")
        title = ApplicationField.get_for_model(Todo).get(field="title")
        self.owner = Form.objects.create(
            name="Settings rendering", content_type=self.status.content_type,
            layout={"rows": [{"columns": 1, "items": [{"id": title.pk}]}]},
        )
        self.owner_content_type = ContentType.objects.get_for_model(Form)
        self.title = title
        from bloomerp.models.users.user_object_layout_preference import (
            UserObjectLayoutPreference,
        )

        self.preference = UserObjectLayoutPreference.objects.create(
            user=self.admin_user, name="Detail settings rendering",
            content_type=self.status.content_type, layout=self.owner.layout,
        )
        self.todo = Todo.objects.create(title="Render settings")

    def _settings_url(self, response: HttpResponse) -> bool:
        """Verify the returned gear points at the authorized owner and field."""
        from django.urls import reverse

        soup = BeautifulSoup(response.content, "html.parser")
        button = soup.select_one("[data-layout-edit-item]")
        self.assertIsNotNone(button)
        url = button["data-layout-edit-url"]
        self.assertIn(f"layout_object_id={response.wsgi_request.GET['layout_object_id']}", url)
        self.assertIn(f"layout_object_content_type_id={response.wsgi_request.resolver_match.kwargs['content_type_id']}", url)
        self.assertTrue(url.startswith(reverse(
            "components_field_display_options",
            kwargs={"application_field_id": response.context["item"].id},
        )))
        return True

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Cover existing and unsaved fields, missing owners, and access denial."""
        params = {
            "target_content_type_id": self.status.content_type_id,
            "layout_object_id": self.owner.pk,
        }
        route = {"content_type_id": self.owner_content_type.pk}
        return [
            *[
                RequestScenario(
                    name=f"Detail field {field.field} has settings control", user=self.admin_user,
                    view_kwargs={"content_type_id": ContentType.objects.get_for_model(self.preference).pk},
                    query_params={**params, "layout_object_id": self.preference.pk,
                                  "object_id": self.todo.pk, "field_id": field.pk},
                    expected=ExpectedResult(response_validators=self._settings_url),
                )
                for field in (self.title, self.status)
            ],
            RequestScenario(
                name="Existing field includes settings control", user=self.admin_user,
                view_kwargs=route, query_params={**params, "field_id": self.title.pk},
                expected=ExpectedResult(response_validators=self._settings_url),
            ),
            RequestScenario(
                name="New field includes settings before persistence", user=self.admin_user,
                view_kwargs=route, query_params={**params, "field_id": self.status.pk},
                expected=ExpectedResult(response_validators=self._settings_url),
            ),
            RequestScenario(
                name="No owner omits unusable settings control", user=self.admin_user,
                view_kwargs=route, query_params={
                    "target_content_type_id": self.status.content_type_id,
                    "field_id": self.status.pk,
                },
                expected=ExpectedResult(response_validators=self.does_not_contain_text("data-layout-edit-item")),
            ),
            RequestScenario(
                name="Deleted owner is rejected", user=self.admin_user,
                view_kwargs=route, query_params={**params, "field_id": self.status.pk, "layout_object_id": "00000000-0000-0000-0000-000000000001"},
                expected=ExpectedResult(status_code=404),
            ),
            RequestScenario(
                name="Unpermitted new field is denied", user=self.normal_user,
                view_kwargs=route, query_params={**params, "field_id": self.status.pk},
                expected=ExpectedResult(status_code=403),
            ),
        ]
