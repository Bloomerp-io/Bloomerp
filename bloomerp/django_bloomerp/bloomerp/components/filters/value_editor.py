from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_POST

from bloomerp.components.filters.common import (
    filter_component, request_parameters, resolver_for_request,
)
from bloomerp.filters.resolver import resolve_lookup
from bloomerp.router import router


@router.register(path="components/filters/value_editor", url_name="components_filters_value_editor")
@login_required
@require_POST
@filter_component
def value_editor(request: HttpRequest) -> JsonResponse:
    """Render an editor for a resolved field, optionally restoring its JSON value."""
    params = request_parameters(request)
    filter_field, target = resolver_for_request(request, params).resolve(params.get("field_path"))
    lookup = resolve_lookup(filter_field, target, params.get("lookup_id"))
    if lookup.nested:
        raise ValidationError("Nested lookups use field discovery, not a value editor")
    factory = lookup.get_form_factory()
    field = factory(filter_field.context) if factory else filter_field.context.get_form_field()
    form = forms.Form(initial={"value": params.get("value")})
    form.fields["value"] = field
    return JsonResponse({"widget": form["value"].as_widget()})
