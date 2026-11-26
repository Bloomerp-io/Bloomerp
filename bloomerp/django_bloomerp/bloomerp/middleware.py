from collections.abc import Callable
from functools import partial
from threading import current_thread

from django.contrib.auth import HASH_SESSION_KEY, SESSION_KEY, get_user_model
from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.cache import add_never_cache_headers, patch_vary_headers
from django.utils.deprecation import MiddlewareMixin
from django_htmx.http import HttpResponseClientRedirect

IMPERSONATED_USER_SESSION_KEY = "bloomerp_impersonated_user_id"


class UserImpersonationMiddleware:
    """Apply the selected user while keeping the administrator's Django login."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        """Store the downstream HTTP request handler."""
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """Resolve both identities and dispatch the request as the selected user."""
        target_id = request.session.get(IMPERSONATED_USER_SESSION_KEY)
        if target_id is None:
            return self.get_response(request)

        admin = request.user
        target = None
        if admin.is_active and admin.is_superuser:
            target = get_user_model()._default_manager.filter(pk=target_id, is_active=True).first()

        if target is None:
            request.session.pop(IMPERSONATED_USER_SESSION_KEY, None)
            home_url = reverse("bloomerp_home_view")
            if request.headers.get("HX-Request") == "true":
                return HttpResponseClientRedirect(home_url)
            return redirect(home_url)

        session_user_id = request.session.get(SESSION_KEY)
        session_auth_hash = request.session.get(HASH_SESSION_KEY)
        request.impersonator = admin
        request.user = target
        request.auser = partial(self._effective_user, request)
        response = self.get_response(request)

        # A password change for the target can update the session hash through Django.
        if (
            session_auth_hash is not None
            and request.session.get(SESSION_KEY) == session_user_id
            and request.session.get(HASH_SESSION_KEY) != session_auth_hash
        ):
            request.session[HASH_SESSION_KEY] = session_auth_hash

        add_never_cache_headers(response)
        return response

    @staticmethod
    async def _effective_user(request: HttpRequest) -> AbstractBaseUser:
        """Return the same effective identity to asynchronous Django views."""
        return request.user


class HTMXVaryMiddleware:
    """Keep full-page and HTMX response variants in separate cache entries."""

    vary_headers = (
        "HX-Request",
        "HX-History-Restore-Request",
        "HX-Target",
    )

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        patch_vary_headers(response, self.vary_headers)
        return response


class HTMXPermissionDeniedMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = None
        try:
            response = self.get_response(request)
        except Exception as e:
            response = self.process_exception(request, e)
            if response is None:
                raise
        return response

    def process_exception(self, request: HttpRequest, exception: Exception) -> HttpResponse | None:
        """Render a swappable denial for HTMX navigation or a full 403 page."""
        if not isinstance(exception, PermissionDenied):
            return None

        if (
            request.headers.get("HX-Request") == "true"
            and request.headers.get("HX-History-Restore-Request") != "true"
        ):
            response_html = render_to_string("snippets/403.html", request=request)
            return HttpResponse(response_html, status=200)

        response_html = render_to_string("403.html", request=request)
        return HttpResponse(response_html, status=403)


_requests = {}

def current_request() -> HttpRequest:
    try:
        return _requests.get(current_thread().ident, None)
    except:
        return None

class RequestMiddleware(MiddlewareMixin):
    def process_request(self, request: HttpRequest) -> None:
        """Bind the current request and discard obsolete request-token query parameters."""
        from bloomerp.tokens import REQUEST_TOKEN_QUERY_KEYS, request_query_params

        if REQUEST_TOKEN_QUERY_KEYS.intersection(request.GET):
            request.GET = request_query_params(request)
            request.META["QUERY_STRING"] = request.GET.urlencode()
        _requests[current_thread().ident] = request

    def process_response(self, request, response):
        # when response is ready, request should be flushed
        _requests.pop(current_thread().ident, None)
        return response


    def process_exception(self, request, exception):
        # if an exception has happened, request should be flushed too
         _requests.pop(current_thread().ident, None)


class TokenMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = request.headers.get("Authorization")
        if token:
            request.token = token
        response = self.get_response(request)
        return response