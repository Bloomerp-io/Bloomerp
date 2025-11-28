"""
All rights reserved. 
"""
from django.db.models import Q
from django.db.models.query import QuerySet
from django.db.models import CharField, TextField

def string_search_on_queryset(queryset: QuerySet, query: str):
    """
    Function to search in all string fields of a QuerySet.
    Returns a QuerySet filtered by the query in all CharField or TextField attributes.

    Usage:
    ```python
    queryset = MyModel.objects.all()
    queryset = string_search_on_queryset(queryset, 'search query')
    ```
    """
    # Get the model of the QuerySet
    model = queryset.model

    # Check if the model has a string_search_fields attribute
    if hasattr(model, 'string_search_fields') and model.string_search_fields:
        return model.string_search(query)

    else:
        # Get all string fields (CharField and TextField) of the model
        string_fields = [
            field.name for field in model._meta.fields
            if isinstance(field, CharField) or isinstance(field, TextField)
        ]

    # Build a Q object to filter across all string fields
    query_filter = Q()
    for field in string_fields:
        query_filter |= Q(**{f"{field}__icontains": query})

    # Filter the queryset by the query in any of the string fields
    return queryset.filter(query_filter)