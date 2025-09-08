from django.http import HttpResponse
from django.template.loader import render_to_string
from django.core.exceptions import PermissionDenied

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
                response_html = render_to_string('snippets/403.html')
                return HttpResponse(response_html, status=200)
            else:
                response_html = render_to_string('403.html')
                return HttpResponse(response_html, status=403)
                
        return None