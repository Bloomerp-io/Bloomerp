from bloomerp.models.base_bloomerp_model import FieldLayout
from bloomerp.models import ApplicationField
from bloomerp.models.base_bloomerp_model import LayoutSection
from django.db.models import Model
from bloomerp.models import AbstractBloomerpUser
from django.contrib.contenttypes.models import ContentType
from bloomerp.field_types import FieldType
from django.utils.translation import gettext_lazy as _
from bloomerp.models import UserDetailViewPreference

def get_default_layout(content_type:ContentType, user:AbstractBloomerpUser) -> FieldLayout:
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
    
    # TODO: Apply field permissions here in future -> use UserPermissionManager
    
    # Get the model
    model = content_type.model_class()
    layout_sections = []
    if hasattr(model, "field_layout") and model.field_layout:
        field_layout = model.field_layout

        # Keep items as field identifier strings (not PKs)
        for section in field_layout.sections:
            items = [field_str for field_str in section.items]

            layout_sections.append(
                LayoutSection(
                    columns=section.columns,
                    title=section.title,
                    items=items
                )
            )

        return FieldLayout(sections=layout_sections)

    else:
        # Auto generate the layout using field identifiers (strings)
        items = list(fields.exclude(field_type=FieldType.PROPERTY.value).values_list("field", flat=True))
        return FieldLayout(
            sections=[
                LayoutSection(
                    title=_("Details"),
                    items=items,
                    columns=2
                )
            ]
        )
        
        
def create_default_detail_view_preference(content_type:ContentType, user:AbstractBloomerpUser) -> UserDetailViewPreference:
    """Creates a default detail view preference

    Args:
        content_type (ContentType): the content type
        user (AbstractBloomerpUser): the user

    Returns:
        UserDetailViewPreference: the detail view preference object
    """
    # Get the FieldLayout with field identifier strings
    default_layout = get_default_layout(content_type, user)

    # Convert field identifier strings to ApplicationField PKs for storage
    stored_sections = []
    for section in default_layout.sections:
        items_pks = []
        for field_str in section.items:
            af = ApplicationField.objects.filter(content_type=content_type, field=field_str).first()
            if af:
                items_pks.append(af.pk)

        stored_sections.append({
            "title": section.title,
            "columns": section.columns,
            "items": items_pks,
        })

    # Persist the converted layout
    return UserDetailViewPreference.objects.create(
        user=user,
        content_type=content_type,
        field_layout={"sections": stored_sections}
    )
    
        
    
    
    

