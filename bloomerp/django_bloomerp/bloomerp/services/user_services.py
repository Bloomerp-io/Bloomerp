"""
All rights reserved. 
"""
from bloomerp.models import UserListViewPreference
from django.contrib.contenttypes.models import ContentType
from bloomerp.models import AbstractBloomerpUser
from django.db.models.query import QuerySet
from bloomerp.models import ApplicationField
from django.core.cache import cache

def create_default_list_view_preference(user: AbstractBloomerpUser, content_type: ContentType) -> QuerySet[UserListViewPreference]:
    """Creates a default list view preference for a user and model based on the model's fields.
    
    Args:
        user (AbstractBloomerpUser): The user for whom to create the preference.
        content_type (ContentType): The content type for which to create the preference.
    Returns:
        UserListViewPreference: The created list view preference.
    """
    # Create default preference
    return UserListViewPreference.generate_default_for_user(user, content_type)


def get_user_list_view_preference(user: AbstractBloomerpUser, content_type: ContentType, use_cache: bool = True) -> list[ApplicationField]:
    """Gets or generates the list view preference for a particular user and model.
    If no preference exists, a default preference is created based on the model definition.
    
    Optimized to use:
    - Django cache (5 minute TTL by default)
    - select_related to avoid N+1 queries
    - Single query with join instead of id__in subquery
    - Returns list instead of QuerySet for better cache serialization
    
    Args:
        user (AbstractBloomerpUser): The user for whom to get the preference.
        content_type (ContentType): The content type for which to get the preference.
        use_cache (bool): Whether to use cache. Default True. Set to False for admin updates.
    Returns:
        list[ApplicationField]: The application fields for the user's list view preference.
    """
    cache_key = f'list_view_pref:{user.id}:{content_type.id}'
    
    # Try to get from cache first
    if use_cache:
        cached_fields = cache.get(cache_key)
        if cached_fields is not None:
            return cached_fields
    
    # Optimized: Use select_related and fetch preferences with fields in one query
    list_view_preferences = (
        UserListViewPreference.objects
        .filter(
            user=user,
            application_field__content_type=content_type,
        )
        .select_related('application_field', 'application_field__content_type')
    )
    
    # Check if preferences exist without triggering extra query
    # Using list() executes query once and caches results
    preferences_list = list(list_view_preferences)
    
    if not preferences_list:
        # Generate defaults if none exist
        create_default_list_view_preference(user, content_type)
        # Re-fetch with optimization
        list_view_preferences = (
            UserListViewPreference.objects
            .filter(
                user=user,
                application_field__content_type=content_type,
            )
            .select_related('application_field', 'application_field__content_type')
        )
        preferences_list = list(list_view_preferences)
    
    # Extract ApplicationField objects directly from the prefetched data
    # This avoids an additional query
    fields = [pref.application_field for pref in preferences_list]
    
    # Cache for 5 minutes (300 seconds)
    if use_cache:
        cache.set(cache_key, fields, 300)
    
    return fields


def clear_user_list_view_preference_cache(user: AbstractBloomerpUser, content_type: ContentType) -> None:
    """Clears the cached list view preference for a user and content type.
    
    Call this function when:
    - User updates their field preferences
    - Admin modifies ApplicationField records
    - Model schema changes
    
    Args:
        user (AbstractBloomerpUser): The user whose cache to clear.
        content_type (ContentType): The content type to clear cache for.
    """
    cache_key = f'list_view_pref:{user.id}:{content_type.id}'
    cache.delete(cache_key)