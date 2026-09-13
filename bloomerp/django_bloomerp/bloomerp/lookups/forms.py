"""Build lookup editors from resolved application fields."""
from bloomerp.lookups.definition import BoundLookup, FilterFieldContext


def build_lookup_form_field(lookup, application_field):
    context = FilterFieldContext(
        field_type=application_field.get_field_type(),
        application_field=application_field,
        related_model=application_field.get_related_model(),
    )
    factory = BoundLookup.normalize(lookup).get_form_factory()
    return factory(context) if factory else context.get_form_field()


def render_lookup(lookup, application_field, name_override=None):
    return build_lookup_form_field(lookup, application_field).widget.render(
        name_override or application_field.field, None,
    )
