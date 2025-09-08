from django.db.models import Model
from django.contrib.contenttypes.models import ContentType
from bloomerp.models.core import ApplicationField, BloomerpModel
from django.db.models.query import QuerySet
from django.db.models import Q, Model, CharField, TextField
from django.apps import apps


def get_related_models(model:Model, relations:list[str] = ['ForeignKey','ManyToManyField']) -> list[Model]:
    """
    This function returns a list of related models for a given model
    """
    related_models = []
    for field in model._meta.get_fields():
        try:
            if field.get_internal_type() in relations:
                related_models.append(field.related_model)
        except:
            pass
    return related_models 

def get_foreign_occurences_for_model(model:Model) -> list[Model]:
    """
    This function returns a list of models that have a foreign key relationship with the given model
    """
    foreign_occurences = []
    content_types = ContentType.objects.all()
    for content_type in content_types:
        if content_type.model_class():
            related_models = get_related_models(content_type.model_class())
            if model in related_models:
                foreign_occurences.append(content_type.model_class())
    return foreign_occurences

def get_attribute_name_for_foreign_key(model:Model, related_model:Model) -> str:
    """
    This function returns the attribute name of the foreign key field of the related model in the model
    """
    for field in model._meta.get_fields():
        try:
            
            if field.many_to_one and field.related_model == related_model:
                return (field.name, "many_to_one")
            if field.many_to_many and field.related_model == related_model:
                return (field.name, "many_to_many")

        except:
            pass

    return None, None

def get_file_fields_dict_for_model(model:Model) -> list[dict[str, bool]]:
    """
    This function returns a list of file fields for a given model.

    Example:
    file_fields_dict_for_model(User) -> [{'name': 'profile_picture', 'allowed_extensions': ['__all__'], 'required': True}]

    """
    file_fields = []
    for field in model._meta.get_fields():
        try:
            if field.get_internal_type() == 'FileField':
                file_fields.append(
                    {"name": field.name, 
                     "allowed_extensions": ['__all__'],
                     "required": not field.blank 
                    }
                )
            elif field.get_internal_type() == 'BloomerpFileField':
                file_fields.append(
                    {
                        "name": field.name,
                        "allowed_extensions": field.allowed_extensions,
                        "required": not field.blank
                    }
                )
        except:
            pass
    return file_fields

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
def get_list_view_url(model:Model, type='relative') -> str:
    """
    This function returns the list view url for a given model.
    """
    if type == 'relative':
        return model_name_plural_underline(model) + '_list'
    elif type == 'absolute':
        return model_name_plural_slug(model) + '/list/'

def get_create_view_url(model:Model, type='relative') -> str:
    """
    This function returns the create view url for a given model.

    Example:
        get_create_view_url(User) -> 'users_add'

        get_create_view_url(User, type='absolute') -> 'users/add/'
    """
    if type == 'relative':
        return model_name_plural_underline(model) + '_add'
    elif type == 'absolute':
        return model_name_plural_slug(model) + '/add/'
    
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
# Search models
# ---------------------------------
def search_content_types_by_query(query:str) -> list[ContentType]:
    """
    This function returns a list of ContentTypes that contain the query in their verbose_name_plural.
    """
    content_types = ContentType.objects.all()
    search_results = []

    for content_type in content_types:
        if query.lower() in content_type.model_class()._meta.verbose_name_plural.lower():
            search_results.append(content_type)
    return search_results

def search_objects_by_content_types(query:str, content_types:list[ContentType], limit:int, user=None) -> list[dict[str, QuerySet]]:
    '''Searches objects via content types
    
    Args:
        query: the given query
        content_types: list of content types which should be queries
        limit: limit results to this number of objects

    Returns:
        list of dictionaries containing the model name and the matching objects
    '''
    results = []

    for content_type in content_types:
        model = content_type.model_class()

        if model == ContentType:
            continue

        try:
            if not user.has_perm(f'{model._meta.app_label}.view_{model._meta.model_name}'):
                continue
            
            if issubclass(model, BloomerpModel) and getattr(model, 'allow_string_search', False):
                    # Perform string search using the static method
                matching_objects = model.string_search(query)
            else:
                if hasattr(model, 'allow_string_search') and not model.allow_string_search:
                    continue

                model.string_search = classmethod(string_search)

                matching_objects = model.string_search(query)
            
            # If there are matching objects, add them to the results
            if matching_objects.exists() and limit:
                if len(matching_objects) > limit:
                    matching_objects = matching_objects[0:limit]

                results.append({
                    "model_name": model._meta.verbose_name_plural,
                    "objects": matching_objects
                })
        except:
            pass

    return results
                

# ---------------------------------
# OTHER
# ---------------------------------
def get_initials(object:Model) -> str:
    """
    This function returns the initials of the object.
    """
    return ''.join([word[0].upper() for word in object.__str__().split()])[0:2]


def stringify_object(object: Model) -> str:
    """
    Returns a robust string representation of a Django model instance, 
    handling different field types and potential errors gracefully.

    Parameters:
    object (Model): A Django model instance.

    Returns:
    str: String representation of the object with field names and values.
    """
    object_string = ''

    # Get model and fields
    model = object._meta.model
    fields = model._meta.fields

    object_string += f'Object: {object.__str__()} | ID {object.pk}\n'
    object_string += f'Object from model: {model._meta.verbose_name}\n'
    object_string += f'Database table: {model._meta.db_table} \n\n'
    object_string += 'Fields:\n'

    for field in fields:
        field_name = field.name
        try:
            # Get the field value
            value = getattr(object, field_name)

            # Handle special cases for field types
            if hasattr(value, '__str__'):
                # Convert to string with truncation if necessary
                value_str = str(value)[:100] + ' (first 100 chars shown)' if len(str(value)) > 100 else str(value)
            else:
                value_str = str(value)

            # Add field name and value to the output string
            object_string += f'{field_name}: {value_str}\n'
        except Exception as e:
            # Log or include information about the error
            object_string += f'{field_name}: [Error retrieving value: {str(e)}]\n'

    return object_string




