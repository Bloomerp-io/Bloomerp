from django.db import models
from django.contrib.contenttypes.models import ContentType
from django.conf import settings
from bloomerp.models.application_field import ApplicationField
from django.db.models import Case, When
from django.db.models import BooleanField, Case, When, Subquery, OuterRef
from bloomerp.models.base_bloomerp_model import BloomerpModel
from bloomerp.models.users.user import AbstractBloomerpUser
from typing import Self
from django.db.models import QuerySet


class UserDetailViewPreference(models.Model):
    class Meta(BloomerpModel.Meta):
        managed = True
        db_table = 'bloomerp_user_detail_view_preference'
        unique_together = ('user', 'application_field')

    POSITION_CHOICES = [
        ('LEFT','Left'), ('CENTER','Center'),('RIGHT','Right')
    ]

    allow_string_search = False

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE,
        related_name = 'detail_view_preference'
        )
    application_field = models.ForeignKey(
        ApplicationField, 
        on_delete=models.CASCADE
        )
    position = models.CharField(
        max_length=10, 
        choices=POSITION_CHOICES
        )

    def get_application_fields_info(content_type_id, user):
        
        is_used_subquery = Subquery(
            UserDetailViewPreference.objects.filter(
                user=user,
                application_field=OuterRef('pk')
            ).values('application_field').annotate(is_used=Case(
                When(pk=OuterRef('pk'), then=True),
                default=True,
                output_field=BooleanField()
            )).values('is_used')[:1]
        )

        position = UserDetailViewPreference.objects.filter(
            user=user,
            application_field=OuterRef('pk')
        ).values('position')[:1]

        application_fields_info = ApplicationField.objects.filter(
            content_type_id=content_type_id
        ).annotate(
            is_used=is_used_subquery,
            position=position
        ).values(
            'field',
            'id',
            'is_used',  
            'position'
        )

        return list(application_fields_info)


    @classmethod
    def generate_default_for_user(cls, user: AbstractBloomerpUser, content_type: ContentType) -> QuerySet[Self]:
        '''
        Method that generates default detail view preference for a user.
        '''
        application_fields = ApplicationField.objects.filter(content_type=content_type)
        
        # Exclude some application fields
        application_fields = application_fields.exclude(
            field_type__in=['ManyToManyField', 'OneToManyField']
        )

        # Exclude some more fields
        application_fields = application_fields.exclude(
            field='id'
        )
        
        
        for application_field in application_fields:
            preference, created = UserDetailViewPreference.objects.get_or_create(
                user=user,
                application_field=application_field,
                position='LEFT'
            )
            
        return UserDetailViewPreference.objects.filter(user=user, application_field__content_type=content_type)
