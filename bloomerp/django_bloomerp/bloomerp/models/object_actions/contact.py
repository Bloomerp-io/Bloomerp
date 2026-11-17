from django.db.models import Model

from bloomerp.models.definition import ObjectHTMLAction
from bloomerp.services.object_contact_services import (
    contact_fields,
    object_contact_context,
)


def contact_action(model: type[Model]) -> ObjectHTMLAction | None:
    """Offer the existing contact controls for models with supported contact fields."""
    if not contact_fields(model):
        return None
    return ObjectHTMLAction(
        id="contact",
        template_name="components/objects/details/contact_actions.html",
        context_func=object_contact_context,
    )
