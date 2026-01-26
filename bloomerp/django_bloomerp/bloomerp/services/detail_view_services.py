from bloomerp.models import ApplicationField
from bloomerp.models.base_bloomerp_model import LayoutSection
from django.db.models import Model
from bloomerp.models.base_bloomerp_model import BloomerpModel
from bloomerp.models import AbstractBloomerpUser
from django.contrib.contenttypes.models import ContentType
from bloomerp.field_types import FieldType
from django.utils.translation import gettext_lazy as _
from bloomerp.models import UserDetailViewPreference

def get_default_layout(content_type:ContentType, user:AbstractBloomerpUser) -> list[LayoutSection]:
    """Generates a default layout for a particular user

    Args:
        model (Model | AbstractBloomerpUser): the given model
        user (AbstractBloomerpUser): the user object

    Returns:
        list[LayoutSection]: list of layouts
    """
    # 1. Get the fields
    fields = ApplicationField.objects.filter(
        content_type=content_type,
    )
    
    # TODO
    # 2. Check which fields the user has access to
    
    # Get the model
    model : BloomerpModel | Model = content_type.model_class()
    layout = []
    if hasattr(model, "field_layout") and model.field_layout:
        field_layout = model.field_layout
        
        # Transform the fields into application fields
        for section in field_layout:
            items = []
            for field_str in section.items:
                items.append(fields.filter(field=field_str).first().pk)
                
            layout.append(
                LayoutSection(
                    columns=section.columns,
                    title=section.title,
                    items=items
                )
            )
        
        return layout
        
    else:
        # Auto generate the layout
        items = list(fields.exclude(field_type=FieldType.PROPERTY.value).values_list("id"))
        return [
            LayoutSection(
                title=_("Details"),
                items=items,
                columns=2
            )
        ]
        
        
def create_default_detail_view_preference(content_type:ContentType, user:AbstractBloomerpUser) -> UserDetailViewPreference:
    """Creates a default detail view preference

    Args:
        content_type (ContentType): the content type
        user (AbstractBloomerpUser): the user

    Returns:
        UserDetailViewPreference: the detail view preference object
    """
    return UserDetailViewPreference.objects.create(
        user=user,
        content_type=content_type,
        field_layout=[i.model_dump() for i in get_default_layout(content_type, user)]
    )
    
        
    
    
    

