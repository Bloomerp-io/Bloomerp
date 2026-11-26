from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse

from bloomerp.router import router
from bloomerp.services.preference_services import PreferenceManager


@router.register(
    path="components/preferences/new_preference/<str:model>/",
    url_name="components_new_preference",
)
@login_required
def new_preference(request: HttpRequest, model: str) -> HttpResponse:
    """Create and select a named copy so the chooser can refresh its region."""
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    manager = PreferenceManager(request.user)
    preference_model = manager.resolve_model(model)
    if preference_model is None:
        return HttpResponse("Unknown preference model.", status=404)

    name = request.POST.get("name", "").strip()
    if not name:
        return HttpResponse("A preference name is required.", status=400)
    if len(name) > 255:
        return HttpResponse("The preference name is too long.", status=400)

    scope = preference_model.normalize_scope(request.POST.dict())
    if len(scope) != len(preference_model.preference_scope_fields):
        return HttpResponse("Preference scope is required.", status=400)
    manager.create(preference_model, name=name, scope=scope)
    return HttpResponse(status=204)
