

from django.db.models import QuerySet

from bloomerp.filters.definition import FilterFieldGroup
from bloomerp.models.application_field import ApplicationField


def application_fields_to_filter_field_groups(
    application_fields:QuerySet[ApplicationField]
) -> list[FilterFieldGroup]:
    """Converts application fields to filter field groups

    Args:
        application_fields (QuerySet[ApplicationField]): The application fields

    Returns:
        list[FilterFieldGroup]: the groups of filters
    """
    pass