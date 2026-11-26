import logging

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.forms import ModelChoiceField
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from bloomerp.middleware import IMPERSONATED_USER_SESSION_KEY
from bloomerp.router import router

logger = logging.getLogger(__name__)


@router.register(
    path="components/ui/sidebar/view-as-user/",
    url_name="components_view_as_user",
)
@never_cache
@require_POST
@csrf_protect
def view_as_user(request: HttpRequest) -> HttpResponse:
    """Apply or clear the effective user submitted from the account menu."""
    admin = getattr(request, "impersonator", request.user)
    if not (admin.is_active and admin.is_superuser):
        raise PermissionDenied

    if request.POST.get("action") == "stop":
        previous_id = request.session.pop(IMPERSONATED_USER_SESSION_KEY, None)
        if previous_id is not None:
            request.session.cycle_key()
            logger.info("User %s stopped viewing as user %s", admin.pk, previous_id)
        return redirect("bloomerp_home_view")

    users = (
        get_user_model()._default_manager.filter(is_active=True).exclude(pk=admin.pk)
    )
    try:
        target = ModelChoiceField(queryset=users).clean(
            request.POST.get("view_as_user")
        )
    except ValidationError:
        messages.error(request, _("Choose an active user to continue."))
        return redirect("bloomerp_home_view")

    previous_id = request.session.get(IMPERSONATED_USER_SESSION_KEY)
    request.session[IMPERSONATED_USER_SESSION_KEY] = str(target.pk)
    request.session.cycle_key()
    logger.info(
        "User %s started viewing as user %s (previous user: %s)",
        admin.pk,
        target.pk,
        previous_id,
    )
    return redirect("bloomerp_home_view")
