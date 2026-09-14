"""Exercise analytics filtering through the tile-rendering HTTP endpoint."""
import json

from bs4 import BeautifulSoup
from django.contrib.contenttypes.models import ContentType

from bloomerp.filters.definition import Filter, FilterCondition
from bloomerp.models.filters.filter import SavedFilter
from bloomerp.models.application_field import ApplicationField
from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from bloomerp.workspaces.dataview_tile.model import DataViewTileConfig
from bloomerp.models.workspaces.tile import Tile
from bloomerp.models.workspaces.workspace import Workspace
from bloomerp.tests.base import BloomerpComponentTestCase, ExpectedResult, RequestScenario
from bloomerp.workspaces.analytics_tile.model import AnalyticsTileConfig, AnalyticsTileFilter, FieldConfig


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
