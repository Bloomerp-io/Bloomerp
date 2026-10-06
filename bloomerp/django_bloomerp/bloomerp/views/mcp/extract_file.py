from django.contrib.auth.decorators import login_required
from django.http import HttpRequest
from django.http import HttpResponse
from bloomerp.router import router

# @router.register()
@login_required
def extract_file(request: HttpRequest) -> HttpResponse:
    """Extracts the content from a file.

    """
    



