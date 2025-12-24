from django.db import models
from django.contrib.contenttypes.models import ContentType
from django.db.models import QuerySet
from django.forms import ValidationError
from django.utils.translation import gettext as _
from django.urls import reverse, NoReverseMatch
from typing import Self
from bloomerp.models.base_bloomerp_model import BloomerpModel
from bloomerp.models.application_field import ApplicationField
from bloomerp.models.mixins import (
    AbsoluteUrlModelMixin,
    StringSearchModelMixin,
)
from django.conf import settings
from bloomerp.models.users.user import AbstractBloomerpUser

class UserListViewField(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,related_name = 'list_view_preference')
    application_field = models.ForeignKey(ApplicationField, on_delete=models.CASCADE)

    @property
    def field_name(self):
        return (self.application_field.field).replace('_', ' ').title()

    class Meta(BloomerpModel.Meta):
        managed = True
        db_table = 'bloomerp_user_list_view_preference'
        unique_together = ('user', 'application_field')


    @classmethod
    def generate_default_for_user(cls, user: AbstractBloomerpUser, content_type: ContentType) -> QuerySet[Self]:
        '''
        Method that generates default list view preference for a user.
        
        Optimized to use bulk_create instead of loop with get_or_create,
        reducing N queries to 2 queries (1 fetch + 1 bulk insert).
        '''
        application_fields = (
            ApplicationField.objects
            .filter(content_type=content_type)
            .exclude(
                field_type__in=['ManyToManyField', 'OneToManyField']
            )
            .exclude(
                field__in=['id', 'created_by', 'updated_by', 'datetime_created', 'datetime_updated']
            )[:5]  # Limit in database, not Python
        )
        
        # Bulk create all preferences at once (single INSERT with multiple rows)
        preferences_to_create = [
            UserListViewField(
                user=user,
                application_field=application_field
            )
            for application_field in application_fields
        ]
        
        # Use ignore_conflicts to handle race conditions where preferences might already exist
        UserListViewField.objects.bulk_create(
            preferences_to_create,
            ignore_conflicts=True
        )
            
        return UserListViewField.objects.filter(user=user, application_field__content_type=content_type)


class Link(
    AbsoluteUrlModelMixin,
    StringSearchModelMixin,
    models.Model,
):
    class Meta(BloomerpModel.Meta):
        managed = True
        db_table = 'bloomerp_link'

    LEVEL_TYPES = [
        ('DETAIL', 'Detail'),
        ('LIST', 'List'),
        ('APP', 'App'),
    ]

    name = models.CharField(max_length=255)
    url = models.CharField(max_length=255, help_text=_("The name of the URL pattern for the link. Can either be a Django URL name or a full URL (absolute)."))
    level = models.CharField(max_length=255, choices=LEVEL_TYPES, help_text=_("The level of the link."))
    is_absolute_url = models.BooleanField(
        default=True,
        help_text=_("Signifies whether the URL is a normal (absolute) URL or a Django URL name. Set to True when using a normal URL.")
        )
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, null=True, blank=True, help_text=_("The content type for the link. Required for detail and list levels."))
    description = models.TextField(null=True, blank=True, help_text=_("Description of the link"))
    
    string_search_fields = ['name', 'url', 'description']
    allow_search = False

    def __str__(self):
        return self.name
    
    def clean(self):
        errors = {}

        # Check if the level type is valid
        if self.level not in [level[0] for level in self.LEVEL_TYPES]:
            errors['level'] = _("Invalid level type")

        # Check if the content type is set for the detail level or list level
        if self.level in ['DETAIL', 'LIST'] and not self.content_type:
            errors['content_type'] = _("Content type must be set for the detail or list level")
        
        # Check if the content type is not set for the app level
        if self.level == 'APP' and self.content_type:
            errors['content_type'] = _("Content type must not be set for the app level")
        
        # If not an absolute URL, check if the reverse works
        if not self.is_absolute_url:
            try:
                reverse(self.url_name)
            except:
                errors['url_name'] = _("The URL name does not match any URL pattern. Set is_absolute_url to True or give a valid URL name.")

        # If the URL is not a Django URL name, and has been saved before, it cannot be changed
        if not self.is_absolute_url and self.pk:
            old_link = Link.objects.get(pk=self.pk)
            if old_link.url != self.url:
                errors['url'] = _("The URL cannot be changed for a link that is not an absolute URL.")

        # Make sure the Link is valid
        if not self.is_valid():
            errors['url'] = _("The URL is not valid.")

        if errors:
            raise ValidationError(errors)

        return super().clean()
    
    def create_default_list_links_for_content_type(content_type: ContentType, output='dict') -> dict:
        """
        Function that creates default links for a content type.

        Output can be either a dictionary or a list of links.

        The default links are:
            - List link
            - App link
            - Create link
            - Bulk upload link
        """
        from bloomerp.utils.models import (
            get_list_view_url,
            get_create_view_url,
            get_model_dashboard_view_url,
            get_bulk_upload_view_url
        )
        # Get the model name
        model = content_type.model_class()

        # Create the list view link
        list_link, created = Link.objects.get_or_create(
            name = _(f"{model._meta.verbose_name.title()} list"),
            url = get_list_view_url(model),
            level = 'LIST',
            content_type = content_type,
            description = _(f"List view for {model._meta.verbose_name}"),
            is_absolute_url = False
        )        
        
        # Create the app link
        app_link, created = Link.objects.get_or_create(
            name = _(f"{model._meta.verbose_name.title()} App"),
            url = get_model_dashboard_view_url(model),
            level = 'APP',
            content_type = content_type,
            description = _(f"App view for {model._meta.verbose_name}"),
            is_absolute_url = False
        )

        # Create the create link
        create_link, created = Link.objects.get_or_create(
            name = _(f"Create {model._meta.verbose_name.title()}"),
            url = get_create_view_url(model),
            level = 'LIST',
            content_type = content_type,
            description = _(f"Create view for {model._meta.verbose_name}"),
            is_absolute_url = False
        )

        # Create the bulk upload link
        bulk_upload_link, created = Link.objects.get_or_create(
            name = _(f"Bulk Upload {model._meta.verbose_name.title()}"),
            url = get_bulk_upload_view_url(model),
            level = 'LIST',
            content_type = content_type,
            description = _(f"Bulk upload view for {model._meta.verbose_name}"),
            is_absolute_url = False
        )

        return {
            'list_link': list_link,
            'app_link': app_link,
            'create_link': create_link,
            'bulk_upload_link': bulk_upload_link
        }

    def create_default_detail_links_for_content_type(content_type: ContentType) -> dict:
        '''
        Function that creates default links for a content type.
        The default links are:
            - Detail link
            - Update link
        '''
        from bloomerp.utils.models import get_detail_view_url, get_update_view_url
        model = content_type.model_class()

        # Create the detail view link
        detail_link, created = Link.objects.get_or_create(
            name = _(f"{model._meta.verbose_name.title()} detail"),
            url = get_detail_view_url(model),
            level = 'DETAIL',
            content_type = content_type,
            description = _(f"Detail view for {model._meta.verbose_name}"),
            is_absolute_url = False
        )

        # Create the update view link
        update_link, created = Link.objects.get_or_create(
            name = _(f"Update {model._meta.verbose_name.title()}"),
            url = get_update_view_url(model),
            level = 'DETAIL',
            content_type = content_type,
            description = _(f"Update view for {model._meta.verbose_name}"),
            is_absolute_url = False
        )

        return {
            'detail_link': detail_link,
            'update_link': update_link
        }

    def get_list_links_for_content_types(content_types: QuerySet, name=None) -> list[dict]:
        '''
        Function that returns the links for a particular content type. 
        If a query is provided, the links will be additionally filtered by name.

        Args:
            content_types: QuerySet[ContentType]
            name: str

        Returns:
            [{'model_name': str, 'links': QuerySet[Link]}]
        '''
        links_info = []

        for content_type in content_types:
            links = Link.objects.filter(content_type=content_type, level='LIST')
            if name:
                links = links.filter(name__icontains=name)
            
            links_info.append({
                'model_name': content_type.model_class()._meta.verbose_name,
                'links': links
            })

        return links_info
    
    def detail_view_tab_links(content_type: ContentType) -> QuerySet:
        '''
        Method that returns the detail view tab links for a content type.
        '''
        qs = Link.objects.filter(content_type=content_type, level='DETAIL') 
        
        for link in qs:
            if link.number_of_args() > 1:
                # Exclude links that require more than one argument
                qs = qs.exclude(pk=link.pk)

        return qs

    @property
    def model_name(self) -> str:
        '''
        Property that returns the model name of the link.
        '''
        if self.content_type:
            return self.content_type.model_class()._meta.verbose_name
        else:
            return None
        
    def requires_args(self) -> bool:
        '''
        Method that checks if the link requires arguments.
        '''
        if self.is_absolute_url:
            return False
        else:
            try:
                reverse(self.url)
                return False
            except NoReverseMatch:
                return True

    def to_absolute_url(self) -> str:
        from django.urls import reverse
        if self.is_absolute_url:
            return self.url
        else:
            try:
                return reverse(self.url)
            except:
                pass

    def get_args(self) -> list:
        '''
        Returns the arguments required for the link.
        '''
        from django.urls import get_resolver
        if self.is_absolute_url:
            return []
        else:
            try:
                resolver = get_resolver()
                return resolver.reverse_dict[self.url][0][0][1]
            except Exception as e:
                return []

    def number_of_args(self) -> int:
        '''Returns the number of args required for the link.'''
        return len(self.get_args())

    def is_external_url(self) -> bool:
        '''
        Method that checks if the link is an external URL.
        External URLs are URLs that are not part of the application.

        Example:
            - https://www.google.com
            - https://www.example.com

        So will return True if the link has www. or http in it.
        
        '''
        if not self.is_absolute_url:
            return False
        else:
            return 'www.' in self.url or 'http' in self.url

    def is_valid(self) -> bool:
        '''
        Method that checks if the link is valid.
        '''
        try:
            if self.is_absolute_url:
                return True
            else:
                from django.urls import get_resolver
                resolver = get_resolver()
                resolver.reverse_dict[self.url]
                return True
        except:
            return False


class UserDetailViewTab(
    AbsoluteUrlModelMixin,

    models.Model
    ):
    class Meta(BloomerpModel.Meta):
        managed = True
        db_table = 'bloomerp_user_detail_view_tab'
        unique_together = ('user','link')

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    link = models.ForeignKey(Link, help_text=_("The link to be displayed in the detail view tab"), on_delete=models.CASCADE)

    allow_string_search = False

    def get_detail_view_tabs(user:AbstractBloomerpUser, content_type:ContentType) -> QuerySet[Self]:
        '''
        Returns the detail view tabs for the user and content type.
        '''
        qs = UserDetailViewTab.objects.filter(user=user, link__content_type=content_type, link__level='DETAIL')
        return qs

    @classmethod
    def generate_default_for_user(cls, user: AbstractBloomerpUser, content_type: ContentType) -> QuerySet[Self]:
        '''
        Method that generates default detail view tabs for a user.
        '''
        links : QuerySet[Link] = Link.detail_view_tab_links(content_type)
        
        for link in links:
            UserDetailViewTab.objects.get_or_create(
                user=user,
                link=link
            )
            
        return UserDetailViewTab.objects.filter(user=user, link__content_type=content_type)

    def __str__(self):
        return str(self.user) + ' ' + str(self.link.name)

    def clean(self):
        errors = {}

        # Check if the link is a detail link
        if self.link.level != 'DETAIL':
            errors['link'] = _("Link must be a detail link")

        if self.link.number_of_args() > 1:
            errors['link'] = _("Link can only have one argument (pk) for a detail view tab")

        if errors:
            raise ValidationError(errors)

        return super().clean()


def get_default_workspace():
    from bloomerp.models.workspaces import Widget
    links = Link.objects.all()
    widgets = Widget.objects.all()

    return {
        "content" : [
            {
                "type": "header",
                "data": {"text": "Welcome to your workspace"},
                "size" : 12
            },
            {
                "type": "text",
                "data": {"text": "This is your workspace. You can add widgets, links, and other content here."},
                "size" : 12
            },
            {
                "type": "header",
                "data": {"text": "Example of widget"},
                "size" : 12
            },
            
            {
                "type": "header",
                "data": {"text": "Example of link"},
                "size" : 12
            },
            {
                "type": "link",
                "data": {"link_id": links.first().pk},
                "size" : 12
            },
            {
                "type": "header",
                "data": {"text": "Example of link list"},
                "size" : 12
            },
            {
                "type": "link_list",
                "data": {"links": [links.first().pk, links.last().pk]},
                "size" : 12
            }
        ]
    }

