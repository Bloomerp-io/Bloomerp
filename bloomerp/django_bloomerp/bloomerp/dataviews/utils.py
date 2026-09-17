



from django.http import HttpRequest


def resolve_string_query(request:HttpRequest):
    """Resolves the string query from the query params

    Args:
        request (HttpRequest): request
    """
    return request.GET.get("q")