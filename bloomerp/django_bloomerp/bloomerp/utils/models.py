from typing import Literal

from django.db.models import Model, QuerySet
from django.contrib.contenttypes.models import ContentType
from bloomerp.models import ApplicationField
from django.shortcuts import get_object_or_404

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
    from bloomerp.services.object_services import string_search_on_queryset

    return string_search_on_queryset(cls.objects.all(), query)

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
    from bloomerp.services.object_services import string_search_on_queryset

    return string_search_on_queryset(qs, query)

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
    from bloomerp.services.object_services import string_search_on_queryset

    return string_search_on_queryset(qs, search_value)

def get_object_from_content_type(content_type_id:int, object_id:str) -> Model | None:
    """
    This function returns an object based on the content type id and object id.

    Args:
        content_type_id (int): the content type id of the object
        object_id (str): the id of the object

    Returns:
        the object or None if not found
    """
    try:
        ct = ContentType.objects.get(id=content_type_id)
        model_class = ct.model_class()
        if model_class is None:
            return None
        return model_class.objects.filter(id=object_id).first()
    except ContentType.DoesNotExist:
        return None


def get_object_model_and_content_type_or_404(content_type_id:int, object_id:str) -> tuple[Model, type[Model], ContentType]:
    """Returns the object, model, and content type or a 404 based on the parameters

    Args:
        content_type_id (int): the content type id
        object_id (str): the object id

    Returns:
        tuple[Model, type[Model], ContentType]: the repsonse
    """
    content_type = get_object_or_404(ContentType, id=content_type_id)
    ModelCls = content_type.model_class()
    object = get_object_or_404(ModelCls, id=object_id)
    
    return object, ModelCls, content_type