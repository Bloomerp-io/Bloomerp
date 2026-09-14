"""Saved filter associations shared by workspace and list preferences."""
import json

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils.translation import gettext_lazy as _


class DefaultFiltersMixin(models.Model):
    class Meta:
        abstract = True

    default_filters = models.ManyToManyField(
        'bloomerp.SavedFilter', blank=True,
        related_name='%(class)s_defaults', verbose_name=_('Default Filters'),
    )

    def get_filter_scope(self) -> tuple[str, str]:
        raise NotImplementedError

    def add_default_filter(self, saved_filter) -> None:
        if (saved_filter.scope, saved_filter.identifier) != self.get_filter_scope():
            raise ValidationError('The filter does not belong to this preference scope.')
        self.default_filters.add(saved_filter)

    @property
    def default_filter_records(self) -> list[dict]:
        return [
            {'id': str(record.pk), 'name': record.name, 'filters': record.filters}
            for record in self.effective_preference.default_filters.order_by('pk')
        ]

    @property
    def default_filter_records_json(self) -> str:
        return json.dumps(self.default_filter_records)

    @property
    def default_filter_groups_json(self) -> str:
        return json.dumps([group for record in self.default_filter_records for group in record['filters']])

    def apply_default_filters(self, query):
        """An explicit filter query is the user's complete active selection."""
        query = query.copy()
        if 'filter' not in query:
            query['filter'] = self.default_filter_groups_json
        return query

    def copy_default_filters_to(self, preference) -> None:
        from bloomerp.models.filters.filter import SavedFilter

        with transaction.atomic():
            for record in self.effective_preference.default_filters.order_by('pk'):
                if self.get_filter_scope() != preference.get_filter_scope():
                    scope, identifier = preference.get_filter_scope()
                    record = SavedFilter.objects.create(
                        name=record.name, scope=scope, identifier=identifier,
                        filters=record.filters,
                    )
                preference.add_default_filter(record)
