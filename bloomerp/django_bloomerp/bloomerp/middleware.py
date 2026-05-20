from django.http import HttpRequest, HttpResponse
from django.template.loader import render_to_string
from django.core.exceptions import PermissionDenied
from threading import current_thread
from django.utils.deprecation import MiddlewareMixin

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
    return _requests.get(current_thread().ident, None)


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
