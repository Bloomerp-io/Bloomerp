from django.db import models


class StringSearchModelMixin(models.Model):
    """
    A mixin for models that need to be searchable by a string query.
    """
    allow_string_search: bool = None

    class Meta:
        abstract = True

    @classmethod
    def string_search(cls, query: str):
        '''
        Static method to search in all string fields of the model.
        Returns a QuerySet filtered by the query in all CharField or TextField attributes.
        '''
        from bloomerp.services.object_services import string_search_on_queryset

        return string_search_on_queryset(cls.objects.all(), query)
