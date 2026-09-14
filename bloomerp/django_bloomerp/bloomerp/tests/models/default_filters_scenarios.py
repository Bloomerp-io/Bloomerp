"""Lifecycle scenarios reused by the two default-filter host models."""
from django.core.exceptions import ValidationError

from bloomerp.models.filters.filter import SavedFilter
from bloomerp.filters.definition import Filter, FilterCondition
from bloomerp.tests.base import ModelScenario


def default_filter_scenarios(test, create_args):
    def add_filter(host, *, name='Default', value='David'):
        scope, identifier = host.get_filter_scope()
        record = SavedFilter.objects.create(
            name=f'{name} {host.pk}', scope=scope, identifier=identifier,
            filters=[Filter(connector='AND', conditions=[
                FilterCondition(field_path='first_name', lookup_id='equals', value=value),
            ]).model_dump(mode='json')],
        )
        host.add_default_filter(record)
        return record

    def check_remove(host):
        first = add_filter(host)
        second = add_filter(host, name='Second', value='Kyle')
        host.default_filters.remove(first)
        test.assertEqual(list(host.default_filters.all()), [second])
        test.assertTrue(SavedFilter.objects.filter(pk=first.pk).exists())
        return True

    def check_copy(host):
        record = add_filter(host)
        copied = type(host).copy_preference_for_user(user=test.other_user, source=host, name='Copy')
        test.assertEqual(copied.default_filters.count(), 1)
        copied_record = copied.default_filters.get()
        test.assertEqual(copied_record.filters, record.filters)
        test.assertEqual((copied_record.scope, copied_record.identifier), copied.get_filter_scope())
        copied.default_filters.clear()
        test.assertEqual(host.default_filters.count(), 1)
        return True

    def check_shared(host):
        record = add_filter(host)
        reference = type(host).objects.create(
            **{**create_args(), 'user': test.other_user, 'source_object': host},
        )
        test.assertEqual(reference.default_filter_records[0]['id'], str(record.pk))
        host.default_filters.clear()
        test.assertEqual(reference.default_filter_records, [])
        return True

    def wrong_scope(host):
        record = SavedFilter.objects.create(name='Wrong scope', scope='model', identifier='invalid', filters=[])
        with test.assertRaisesMessage(ValidationError, 'does not belong'):
            host.add_default_filter(record)
        test.assertFalse(host.default_filters.exists())
        return True

    def prepare_deletion(host):
        test.saved_default = add_filter(host)

    return [
        ModelScenario(
            name='New hosts have no default filters', create_args=create_args,
            description='UC: Create a host.\nExpected Result: No default filters are selected.',
            create_validators=lambda host: host.default_filters.count() == 0,
        ),
        ModelScenario(
            name='Removing a default retains the saved filter and other defaults', create_args=create_args,
            description='UC: Remove one of two defaults.\nExpected Result: Only its association is removed.',
            create_validators=check_remove,
        ),
        ModelScenario(
            name='Copies retain defaults with independent associations', create_args=create_args,
            description='UC: Copy a preference.\nExpected Result: Defaults remain usable in the new scope without changing the source.',
            create_validators=check_copy,
        ),
        ModelScenario(
            name='Shared references resolve the owners live defaults', create_args=create_args,
            description='UC: Read a shared preference.\nExpected Result: Resolve its current source defaults.',
            create_validators=check_shared,
        ),
        ModelScenario(
            name='Deleting a host retains its saved filters', create_args=create_args,
            description='UC: Delete a host.\nExpected Result: Its saved filters still exist.',
            post_create=prepare_deletion,
            delete_validators=lambda host: SavedFilter.objects.filter(pk=test.saved_default.pk).exists(),
        ),
        ModelScenario(
            name='Reject a default from another scope', create_args=create_args, create_validators=wrong_scope,
            description='UC: Associate a filter from another scope.\nExpected Result: Raise ValidationError.',
        ),
    ]
