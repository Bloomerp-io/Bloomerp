from django.db import models
from django.db.models import F, Q, Value
from django.db.models.functions import Concat


class StringSearchModelMixin(models.Model):
    """
    A mixin for models that need to be searchable by a string query.
    """
    string_search_fields: list = None  # The list of fields to search in
    allow_string_search: bool = None

    class Meta:
        abstract = True

    @classmethod
    def string_search(cls, query: str):
        '''
        Static method to search in all string fields of the model.
        Returns a QuerySet filtered by the query in all CharField or TextField attributes.
        '''
        # Get all string fields (CharField and TextField) of the model
        if cls.string_search_fields:
            string_fields = cls.string_search_fields
        else:
            string_fields = [
                field.name for field in cls._meta.fields
                if isinstance(field, models.CharField) or isinstance(field, models.TextField)
            ]

        queryset = cls.objects.all()

        # Replace spaces in the query with empty strings

        # Build a Q object to filter across all string fields
        query_filter = Q()
        for field in string_fields:
            if '+' in field:
                concatenated_query = query.replace(' ','')
                concat_fields = field.split('+')
                concat_operation = Concat(*[F(f) if f != ' ' else Value(' ') for f in concat_fields], output_field=models.CharField())
                queryset = queryset.annotate(**{field: concat_operation})
                query_filter |= Q(**{f"{field}__icontains": concatenated_query})
            else:
                query_filter |= Q(**{f"{field}__icontains": query})

        # Filter the queryset by the query in any of the string fields
        return queryset.filter(query_filter)