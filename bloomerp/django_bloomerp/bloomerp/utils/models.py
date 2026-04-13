from typing import Literal

from django.db.models import F, Model, QuerySet, Value
from django.contrib.contenttypes.models import ContentType
from django.db.models.functions import Concat
from bloomerp.models import ApplicationField

from django.db.models.query import QuerySet
from django.db.models import Q, Model, CharField, TextField
from django.apps import apps


def model_name_singular_slug(model:Model) -> str:
    """
    This function returns the model name in a slug format.

    Example:
    
    model_name_slug(User) -> 'user'
    model_name_slug(UserProfile) -> 'user-profile'

    """
    return model._meta.verbose_name_plural.replace(' ', '-')

def model_name_plural_slug(model:Model) -> str:
    """
    This function returns the model name in a plural slug format.

    Example:

    model_name_plural_slug(User) -> 'users'
    model_name_plural_slug(UserProfile) -> 'user-profiles'
    """
    return model._meta.verbose_name_plural.replace(' ', '-').lower()

def model_name_singular_underline(model:Model) -> str:
    """
    This function returns the model name in a singular underline format.

    Example:

    model_name_singular_underline(User) -> 'user'
    model_name_singular_underline(UserProfile) -> 'user_profile'
    """
    return model._meta.verbose_name.replace(' ', '_')

def model_name_plural_underline(model:Model) -> str:
    """
    This function returns the model name in a plural underline format.

    Example:

    model_name_plural_underline(User) -> 'users'
    model_name_plural_underline(UserProfile) -> 'user_profiles'
    """
    return model._meta.verbose_name_plural.replace(' ', '_').lower()

def string_search(cls, query: str):
    '''
    Class method to search in all string fields of the model.
    Returns a QuerySet filtered by the query in all CharField or TextField attributes.

    Can be given to a model as a class method to search in all string fields of the model.

    Usage:
    ```
    model.string_search = classmethod(string_search)

    '''
    # Get all string fields (CharField and TextField) of the model
    if hasattr(cls, 'string_search_fields') and cls.string_search_fields:
        string_fields = cls.string_search_fields
    else:
        string_fields = [
            field.name for field in cls._meta.fields
            if isinstance(field, CharField) or isinstance(field, TextField)
        ]

    # Build a Q object to filter across all string fields
    query_filter = Q()
    for field in string_fields:
        query_filter |= Q(**{f"{field}__icontains": query})

    # Filter the queryset by the query in any of the string fields
    return cls.objects.filter(query_filter)

def string_search_on_qs(qs: QuerySet, query: str):
    '''
    Function to search in all string fields of a QuerySet.
    Returns a QuerySet filtered by the query in all CharField or TextField attributes.

    Usage:
    ```
    qs = MyModel.objects.all()
    qs = string_search_on_qs(qs, 'search query')
    ```
    '''
    # Get the model of the QuerySet
    model = qs.model

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
    return qs.filter(query_filter)

def get_bloomerp_file_fields_for_model(model:Model, output='queryset') -> QuerySet[ApplicationField] | list[str]:
    """
    This function returns a QuerySet of ApplicatonFields for a given model containing BloomerpFileFields.
    """
    content_type = ContentType.objects.get_for_model(model)
    qs = ApplicationField.objects.filter(
        content_type=content_type,
        field_type='BloomerpFileField')
    
    if output == 'queryset':
        return qs
    elif output == 'list':
        return list(qs.values_list('field', flat=True))
    
def get_foreign_key_fields_for_model(model:Model) -> QuerySet[ApplicationField]:
    """
    This function returns a QuerySet of ApplicatonFiels for a given model.
    """
    content_type = ContentType.objects.get_for_model(model)
    return ApplicationField.objects.filter(
        content_type=content_type,
        field_type='ForeignKey')

# ---------------------------------
# URL Related Functions
# ---------------------------------
def get_list_view_url(model:Model, type:Literal['relative', 'absolute']='relative') -> str:
    """
    This function returns the list view url for a given model.
    """
    if type == 'relative':
        return model_name_plural_underline(model) + '_model'
    elif type == 'absolute':
        return model_name_plural_slug(model) + '/'

def get_create_view_url(model:Model, type:Literal['relative', 'absolute']='relative') -> str:
    """
    This function returns the create view url for a given model.

    Example:
        get_create_view_url(User) -> 'users_add'

        get_create_view_url(User, type='absolute') -> 'users/add/'
    """
    if type == 'relative':
        return model_name_plural_underline(model) + '_add'
    elif type == 'absolute':
        return model_name_plural_slug(model) + '/create/'
    
def get_model_dashboard_view_url(model:Model, type='relative') -> str:
    """
    This function returns the dashboard url for a given model.

    Example:
        get_model_dashboard_view_url(User) -> 'users_dashboard'

        get_model_dashboard_view_url(User, type='absolute') -> 'users/dashboard/'
    """
    if type == 'relative':
        return model_name_plural_underline(model) + '_dashboard'
    elif type == 'absolute':
        return model_name_plural_slug(model) + '/'
    
def get_update_view_url(model:Model, type='relative') -> str:
    """
    This function returns the update view url for a given model.

    Example:
        get_update_view_url(User) -> 'users_update'

        get_update_view_url(User, type='absolute') -> 'users/<int_or_uuid:pk>/update/'
    """
    if type == 'relative':
        return model_name_plural_underline(model) + '_detail_update'
    elif type == 'absolute':
        return model_name_plural_slug(model) + '/<int_or_uuid:pk>/update/'

def get_delete_view_url(model:Model, type='relative') -> str:
    """
    This function returns the delete view url for a given model.

    Example:
        get_delete_view_url(User) -> 'users_detail_delete'

        get_delete_view_url(User, type='absolute') -> 'users/<int_or_uuid:pk>/delete/'
    """
    if type == 'relative':
        return model_name_plural_underline(model) + '_detail_delete'
    elif type == 'absolute':
        return model_name_plural_slug(model) + '/<int_or_uuid:pk>/delete/'
    
def get_detail_view_url(model, type='relative') -> str:
    """
    This function returns the detail view url for a given model.

    Example:
        get_detail_view_url(User) -> 'users_detail'

    """
    if type == 'relative':
        return model_name_plural_underline(model) + '_detail_overview'
    elif type == 'absolute':
        return model_name_plural_slug(model) + '/<int_or_uuid:pk>/'

def get_detail_base_view_url(model, type='relative') -> str:
    """
    This function returns the detail view url for a given model.

    Example:
        get_detail_view_url(User) -> 'users_detail'

    """
    if type == 'relative':
        return model_name_plural_underline(model) + '_detail'

def get_bulk_upload_view_url(model:Model, type='relative') -> str:
    """
    This function returns the bulk upload view url for a given model.

    Example:
        get_bulk_upload_view_url(User) -> 'users_bulk_upload
    """
    if type == 'relative':
        return model_name_plural_underline(model) + '_bulk_upload'
    
def get_base_model_route(model:Model, include_slash=True) -> str:
    """
    This function returns the absolute base route for a given model.

    Example:
        get_base_model_route(User) -> 'users/'
        get_base_model_route(UserProfile) -> 'user-profiles/'

    """
    if include_slash:
        return model_name_plural_slug(model) + '/'
    else:
        return model_name_plural_slug(model)
    
def get_document_template_list_view_url(model: Model, type='relative') -> str:
    """
    This function returns the document template list view url for a given model.

    Example:
        get_document_template_list_view_url(Employee) -> 'employees_document_template_list
        get_document_template_list_view_url(Employee, type='absolute') -> 'employees/document-templates/list/'

    """
    if type == 'relative':
        return model_name_plural_underline(model) + '_document_template_list'
    elif type == 'absolute':
        return model_name_plural_slug(model) + '/document-templates/list/'
    
def get_document_template_generate_view_url(model: Model, type='relative') -> str:
    """
    This function returns the document template generate view url for a given model.

    Example:
        get_document_template_generate_view_url(Employee) -> 'employees_document_template_generate
        get_document_template_generate_view_url(Employee, type='absolute') -> 'employees/<int_or_uuid:pk>/document-templates/<int:template_id>/generate/'

    """
    if type == 'relative':
        return model_name_plural_underline(model) + 'detail_document_templates_generate'
    elif type == 'absolute':
        return model_name_plural_slug(model) + '/<int_or_uuid:pk>/document-templates/<int:template_id>/generate/'
    
def get_model_foreign_key_view_url(model:Model, foreign_model:Model, type='relative') -> str:
    """
    This function returns the foreign key view url for a given model.

    Example:
        get_model_foreign_key_view_url(User, UserProfile) -> 'users_detail_user_profiles'
    """
    if type == 'relative':
        return model_name_plural_underline(model) + '_detail_' + model_name_plural_slug(foreign_model)
    if type == 'absolute':
        return model_name_plural_slug(model) + '/<int_or_uuid:pk>/' + model_name_plural_slug(foreign_model) + '/'
    


# ---------------------------------
# OTHER
# ---------------------------------
def get_initials(object:Model) -> str:
    """
    This function returns the initials of the object.
    """
    return ''.join([word[0].upper() for word in object.__str__().split()])[0:2]

def string_search_queryset(qs: QuerySet, search_value: str) -> QuerySet:
        model = qs.model
        string_fields = getattr(model, "string_search_fields", None) or [
            field.name
            for field in model._meta.fields
            if isinstance(field, CharField) or isinstance(field, TextField)
        ]
        if not string_fields:
            return qs.none()

        search_value = search_value or ""
        query_filter = None
        working_qs = qs

        actual_field_names = {
            field.name
            for field in model._meta.fields
            if isinstance(field, CharField) or isinstance(field, TextField)
        }
        token_fields = []

        for field in string_fields:
            if "+" in field:
                concatenated_query = search_value.replace(" ", "")
                concat_fields = field.split("+")
                concat_operation = Concat(
                    *[F(item) if item != " " else Value(" ") for item in concat_fields],
                    output_field=CharField(),
                )
                working_qs = working_qs.annotate(**{field: concat_operation})
                condition = {f"{field}__icontains": concatenated_query}
                for part in concat_fields:
                    if part in actual_field_names:
                        token_fields.append(part)
            else:
                condition = {f"{field}__icontains": search_value}
                if field in actual_field_names:
                    token_fields.append(field)

            if query_filter is None:
                query_filter = Q(**condition)
            else:
                query_filter |= Q(**condition)

        if query_filter is None:
            return qs.none()

        tokens = [token for token in search_value.split() if token]
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

        return working_qs.filter(query_filter)


