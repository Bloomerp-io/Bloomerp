"""
All rights reserved. 
"""
from django.db.models import Q
from django.db.models.query import QuerySet
from django.db.models import CharField, F, TextField, Value
from django.db.models.functions import Concat

from bloomerp.models import User

def string_search_on_queryset(queryset: QuerySet, query: str):
    """
    Search a queryset using the model's configured string search behavior.

    By default this searches all local CharField and TextField fields. Models
    can set ``bloomerp_config.string_search_fields`` to control the fields that
    are searched, including relation paths and concatenated fields such as
    ``first_name+last_name``.

    Usage:
    ```python
    queryset = MyModel.objects.all()
    queryset = string_search_on_queryset(queryset, 'search query')
    ```
    """
    model = queryset.model
    bloomerp_config = getattr(model, "bloomerp_config", None)
    configured_string_fields = getattr(bloomerp_config, "string_search_fields", None)
    if configured_string_fields is None:
        string_fields = [
            field.name
            for field in model._meta.fields
            if isinstance(field, CharField) or isinstance(field, TextField)
        ]
    else:
        string_fields = configured_string_fields

    if not string_fields:
        return queryset.none()

    query = query or ""
    query_filter = None
    working_queryset = queryset

    local_string_field_names = {
        field.name
        for field in model._meta.fields
        if isinstance(field, CharField) or isinstance(field, TextField)
    }
    token_fields = []

    for field in string_fields:
        if "+" in field:
            concatenated_query = query.replace(" ", "")
            concat_fields = field.split("+")
            annotation_name = f"_bloomerp_string_search_{len(token_fields)}"
            concat_operation = Concat(
                *[F(item) if item != " " else Value(" ") for item in concat_fields],
                output_field=CharField(),
            )
            working_queryset = working_queryset.annotate(**{annotation_name: concat_operation})
            condition = {f"{annotation_name}__icontains": concatenated_query}
            for part in concat_fields:
                if part != " ":
                    token_fields.append(part)
        else:
            condition = {f"{field}__icontains": query}
            if configured_string_fields is not None or field in local_string_field_names:
                token_fields.append(field)

        if query_filter is None:
            query_filter = Q(**condition)
        else:
            query_filter |= Q(**condition)

    if query_filter is None:
        return queryset.none()

    tokens = [token for token in query.split() if token]
    token_fields = list(dict.fromkeys(token_fields))
    if len(tokens) > 1 and token_fields:
        tokens_query = None
        for token in tokens:
            token_query = Q()
            for field in token_fields:
                token_query |= Q(**{f"{field}__icontains": token})
            if tokens_query is None:
                tokens_query = token_query
            else:
                tokens_query &= token_query

        if tokens_query is not None:
            query_filter = query_filter | tokens_query

    return working_queryset.filter(query_filter)


class UserCrudManager:
    def __init__(self, user:User):
        self.user = user

    def create_form(self, model_or_content_type):
        pass

    def save_form(self, form):
        pass
    
