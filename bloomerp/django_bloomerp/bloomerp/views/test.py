from django.http import HttpResponse
from shared_utils.registries.route_registry import router

@router.register("/hey/<int:id>/")
def view(request, id):
    
    return HttpResponse("Dude")