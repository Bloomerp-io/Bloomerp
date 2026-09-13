from collections.abc import Callable
from threading import current_thread

from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.template.loader import render_to_string
from django.utils.cache import patch_vary_headers
from django.utils.deprecation import MiddlewareMixin


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

    def process_exception(self, request, exception):
        if isinstance(exception, PermissionDenied):
            if request.headers.get('HX-Request'):
                response_html = render_to_string('snippets/403.html', request=request)
                return HttpResponse(response_html, status=200)
            else:
                response_html = render_to_string('403.html', request=request)
                return HttpResponse(response_html, status=403)
                
        return None


_requests = {}

def current_request() -> HttpRequest:
    try:
        return _requests.get(current_thread().ident, None)
    except:
        return None

class RequestMiddleware(MiddlewareMixin):
    def process_request(self, request):
        _requests[current_thread().ident] = request

    def process_response(self, request, response):
        # when response is ready, request should be flushed
        _requests.pop(current_thread().ident, None)
        return response


    def process_exception(self, request, exception):
        # if an exception has happened, request should be flushed too
         _requests.pop(current_thread().ident, None)
