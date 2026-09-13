"""Analytics queries reuse the canonical filter parser and SQL lookup compiler."""
import json
from types import SimpleNamespace

from django.core.exceptions import ValidationError
from django.db import connection
from django.http import QueryDict
from django.test import SimpleTestCase

from bloomerp.filters.definition import Filter, FilterCondition
from bloomerp.filters.resolver import FilterFieldResolver
from bloomerp.workspaces.analytics_tile.model import AnalyticsTileConfig, AnalyticsTileFilter, get_filtered_query
from bloomerp.workspaces.analytics_tile.utils import analytics_tile_filter_field_factory


class TestAnalyticsQueryFilters(SimpleTestCase):
    def config(self, name='week', **kwargs):
        return AnalyticsTileConfig(query='SELECT 1 AS week;', type='TABLE', filters=[
            AnalyticsTileFilter(field=name, type='numeric'),
        ], **kwargs)

    def params(self, *groups):
        return {'filter': json.dumps([group.model_dump() for group in groups])}

    def condition(self, path='week', value='12', lookup='equals'):
        return FilterCondition(field_path=path, lookup_id=lookup, value=value)

    def test_numeric_or_and_groups(self):
        """
        UC: Two numeric alternatives are combined with an upper bound.
        Expected Result: SQL preserves OR within the first group and AND between groups, with cleaned numbers.
        """
        query = get_filtered_query(self.config(), self.params(
            Filter(connector='OR', conditions=[self.condition(value='1'), self.condition(value='2')]),
            Filter(connector='AND', conditions=[self.condition(value='3', lookup='less_than')]),
        ))
        self.assertIn(' OR ', query)
        self.assertIn(' AND ', query)
        self.assertIn('"week" = 1', query)
        self.assertIn('"week" < 3', query)
        self.assertNotIn(';', query)

    def test_invalid_values_and_unknown_json_fields_fail(self):
        """
        UC: A canonical condition contains an invalid number or unconfigured field.
        Expected Result: Validation rejects the condition instead of silently dropping it.
        """
        for condition in [self.condition(value='bad'), self.condition(path='secret'), self.condition(lookup='missing')]:
            with self.subTest(condition=condition), self.assertRaises(ValidationError):
                get_filtered_query(self.config(), self.params(Filter(connector='AND', conditions=[condition])))

    def test_repeated_shorthand_and_json(self):
        """
        UC: Repeated shorthand accompanies a JSON group.
        Expected Result: All conditions are included with implicit AND.
        """
        params = QueryDict('', mutable=True)
        params.setlist('week__gte', ['1', '2'])
        params['filter'] = self.params(Filter(connector='AND', conditions=[self.condition(value='3')]))['filter']
        query = get_filtered_query(self.config(), params)
        self.assertIn('"week" >= 1', query)
        self.assertIn('"week" >= 2', query)
        self.assertIn('"week" = 3', query)

    def test_shared_alias_and_other_tile_projection(self):
        """
        UC: A shared condition maps to differently named columns, alongside a tile-specific condition.
        Expected Result: Each tile uses its own column; unrelated conditions are omitted.
        """
        configs = [self.config(), self.config('reporting_week')]
        configs[1].filters[0].shared_key = 'week'
        tiles = [SimpleNamespace(pk=index, title=str(index), get_config_object=lambda config=config: config,
                 get_tile_type_definition=lambda: SimpleNamespace(filter_fields_factory=analytics_tile_filter_field_factory))
                 for index, config in enumerate(configs, 1)]
        resolver = FilterFieldResolver(workspace=SimpleNamespace(get_tiles=lambda: tiles))
        params = self.params(Filter(connector='OR', conditions=[
            self.condition(path='shared:week'), self.condition(path='tile_1:week', value='99'),
        ]))
        query = get_filtered_query(configs[1], params, resolver=resolver, tile_id='2')
        self.assertIn('"reporting_week" = 12', query)
        self.assertNotIn('99', query)
        self.assertNotIn(' OR ', query)

    def test_explicit_empty_groups(self):
        """
        UC: An explicitly empty AND or OR group is submitted.
        Expected Result: AND compiles to true and OR compiles to false.
        """
        for connector, expected in [('AND', 'TRUE'), ('OR', 'FALSE')]:
            query = get_filtered_query(self.config(), self.params(Filter(connector=connector)))
            self.assertIn(expected, query)

    def test_other_tile_only_does_not_filter(self):
        """
        UC: Every condition applies to another tile.
        Expected Result: The current tile query is not wrapped with a predicate.
        """
        query = get_filtered_query(self.config(), self.params(Filter(connector='OR', conditions=[self.condition(path='tile_2:week')])), tile_id='1')
        self.assertEqual(query, 'SELECT 1 AS week')

    def test_literal_and_identifier_escaping(self):
        """
        UC: A string value contains SQL syntax and the configured column contains a quote.
        Expected Result: The value stays a quoted literal and the column is quoted as an identifier.
        """
        config = AnalyticsTileConfig(query='SELECT 1', type='TABLE', filters=[AnalyticsTileFilter(field='odd"name', type='text')])
        query = get_filtered_query(config, self.params(Filter(connector='AND', conditions=[self.condition(path='odd"name', value="x'; DROP TABLE users; --")])) )
        self.assertIn('"odd""name"', query)
        prefix = "E" if connection.vendor == "postgresql" else ""
        self.assertIn(prefix + "'x''; DROP TABLE users; --'", query)

    def test_compiled_numeric_groups_select_expected_rows(self):
        """
        UC: Execute an OR group combined with an AND bound on numeric results.
        Expected Result: Only rows satisfying the complete grouped predicate are returned.
        """
        import sqlite3
        config = self.config()
        config.query = 'SELECT 1 AS week UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4'
        query = get_filtered_query(config, self.params(
            Filter(connector='OR', conditions=[self.condition(value='1'), self.condition(value='2', lookup='greater_than')]),
            Filter(connector='AND', conditions=[self.condition(value='4', lookup='less_than')]),
        ))
        # Numeric predicates use SQL common to PostgreSQL and SQLite; this
        # isolated execution check does not require the application's database.
        with sqlite3.connect(':memory:') as connection:
            self.assertEqual(connection.execute(query).fetchall(), [(1,), (3,)])
