"""Request adaptation shared by filter components."""
import json
from functools import wraps

from django.core.exceptions import ValidationError
from django.http import JsonResponse

from bloomerp.filters.resolver import FilterFieldResolver


def filter_component(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except ValidationError as exc:
            return JsonResponse({"errors": exc.messages}, status=400)
        except (ValueError, TypeError) as exc:
            return JsonResponse({"error": str(exc)}, status=400)
    return wrapped


def request_parameters(request):
    if request.method == "GET":
        return request.GET
    if request.content_type == "application/json":
        data = json.loads(request.body)
        if not isinstance(data, dict):
            raise ValidationError("Expected a JSON object")
        return data
    return request.POST


def resolver_for_request(request, params):
    return FilterFieldResolver.for_user(params.get("scope"), params.get("id"), request.user)
