"""Workspace discovery shares logical fields without changing field types."""
from types import SimpleNamespace

from django.test import SimpleTestCase
from django.core.exceptions import ValidationError

from bloomerp.filters.definition import FilterField
from bloomerp.filters.resolver import FilterFieldResolver
from bloomerp.lookups.definition import FilterFieldContext


class TestWorkspaceSharedFields(SimpleTestCase):
    def field(self, name='week', type_id='decimal', related=None, choices=None, model=False):
        application_field = None
        if model:
            application_field = SimpleNamespace(
                related_model_id=related,
                _get_model_field=lambda: SimpleNamespace(choices=choices, flatchoices=choices),
                get_model=lambda: object,
            )
        return FilterField(field=name, label=name, context=FilterFieldContext(
            field_type=SimpleNamespace(id=type_id, lookups=[]),
            application_field=application_field,
        ))

    def resolver(self, *entries):
        tiles = []
        for index, (field, aliases) in enumerate(entries, 1):
            tiles.append(SimpleNamespace(
                pk=index, title=f'Tile {index}',
                get_tile_type_definition=lambda field=field: SimpleNamespace(filter_fields_factory=lambda config: [field]),
                get_config_object=lambda aliases=aliases: SimpleNamespace(get_filter_shared_key=lambda name: aliases.get(name, name)),
            ))
        return FilterFieldResolver(workspace=SimpleNamespace(get_tiles=lambda: tiles))

    def test_default_name_shares_four_tiles(self):
        """
        UC: Four analytics tiles expose a week column.
        Expected Result: One shared Week field resolves to all four SQL targets.
        """
        resolver = self.resolver(*[(self.field(), {}) for _ in range(4)])
        groups = resolver.discover()
        self.assertEqual(len(groups), 1)
        self.assertEqual([field.field for field in groups[0].fields], ['shared:week'])
        self.assertEqual([target.tile_id for _, target in resolver.resolve_all('shared:week')], ['1', '2', '3', '4'])

    def test_alias_shares_analytics_and_dataview(self):
        """
        UC: A dataview and analytics column have different names but the same shared key.
        Expected Result: One logical field retains each backend's actual execution path.
        """
        resolver = self.resolver((self.field(), {}), (self.field('reporting_week', model=True), {'reporting_week': 'week'}))
        self.assertEqual(resolver.discover()[0].fields[0].field, 'shared:week')
        resolved = resolver.resolve_all('shared:week')
        self.assertEqual([(target.backend, target.field_path) for _, target in resolved], [('sql', 'week'), ('django', 'reporting_week')])
        self.assertIsNone(resolver.resolve('shared:week')[0].context.application_field)
        self.assertEqual(resolver.resolve_for_tile('shared:week', '2')[1].field_path, 'reporting_week')
        self.assertIsNone(resolver.resolve_for_tile('shared:week', '99'))

    def test_incompatible_configuration_stays_separate(self):
        """
        UC: Identical names have different FieldTypes, related models, or choices.
        Expected Result: Fields remain tile-specific and no shared path can be resolved.
        """
        pairs = [
            (self.field(), self.field(type_id='text')),
            (self.field(model=True, related=1), self.field(model=True, related=2)),
            (self.field(model=True, choices=[('a', 'A')]), self.field(model=True, choices=[('b', 'B')])),
        ]
        for first, second in pairs:
            with self.subTest(second=second):
                resolver = self.resolver((first, {}), (second, {}))
                self.assertEqual([field.field for group in resolver.discover() for field in group.fields], ['tile_1:week', 'tile_2:week'])
                with self.assertRaises(ValidationError):
                    resolver.resolve_all('shared:week')

    def test_opt_out_and_existing_tile_paths(self):
        """
        UC: A tile opts out of sharing and a saved filter uses an explicit tile path.
        Expected Result: The opted-out field stays separate and saved tile paths remain valid.
        """
        resolver = self.resolver((self.field(), {}), (self.field(), {}), (self.field(), {'week': None}))
        self.assertEqual([field.field for group in resolver.discover() for field in group.fields], ['shared:week', 'tile_3:week'])
        self.assertEqual(resolver.resolve('tile_1:week')[1].tile_id, '1')
        self.assertIsNone(resolver.resolve_for_tile('shared:week', '3'))

    def test_reverse_relations_without_choices(self):
        """
        UC: Two dataview fields represent reverse relations to the same model.
        Expected Result: Missing choices metadata does not break shared discovery.
        """
        fields = [self.field(model=True, related=1) for _ in range(2)]
        for field in fields:
            field.context.application_field._get_model_field = lambda: SimpleNamespace()
        resolver = self.resolver(*[(field, {}) for field in fields])
        self.assertEqual(resolver.discover()[0].fields[0].field, 'shared:week')
        self.assertIsNotNone(resolver.resolve('shared:week')[0].context.application_field)

    def test_inaccessible_fields_are_not_shared(self):
        """
        UC: One matching field is excluded by the resolver's existing access check.
        Expected Result: Discovery does not expose a shared path targeting that field.
        """
        first, second = self.field(), self.field()
        resolver = self.resolver((first, {}), (second, {}))
        resolver._can_access = lambda field: field is first
        self.assertEqual([field.field for group in resolver.discover() for field in group.fields], ['tile_1:week'])
        with self.assertRaises(ValidationError):
            resolver.resolve_all('shared:week')
