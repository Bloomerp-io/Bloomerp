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
        """Append persisted defaults to the filters supplied by the request."""
        query = query.copy()
        default_filters = self.default_filter_groups_json
        if default_filters == '[]':
            return query

        if hasattr(query, 'appendlist'):
            query.appendlist('filter', default_filters)
        elif 'filter' not in query:
            query['filter'] = default_filters
        else:
            request_filters = query['filter']
            query['filter'] = (
                [*request_filters, default_filters]
                if isinstance(request_filters, list)
                else [request_filters, default_filters]
            )
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
