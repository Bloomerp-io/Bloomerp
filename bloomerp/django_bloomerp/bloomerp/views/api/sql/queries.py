import json

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponseNotAllowed, JsonResponse

from bloomerp.models.workspaces.sql_query import SqlQuery
from bloomerp.router import router


@router.register(path="api/sql/queries/", name="api_sql_queries")
@login_required
def sql_queries(request: HttpRequest) -> JsonResponse | HttpResponseNotAllowed:
    if request.method == "GET":
        return _list_queries(request)

    if request.method == "POST":
        return _save_query(request)

    return HttpResponseNotAllowed(["GET", "POST"])


def _list_queries(request: HttpRequest) -> JsonResponse:
    queries = (
        SqlQuery.objects.filter(created_by=request.user)
        .order_by("name", "id")
        .values("id", "name", "query")
    )

    return JsonResponse({"queries": list(queries)})


def _save_query(request: HttpRequest) -> JsonResponse:
    if not request.user.has_perm("bloomerp.execute_sql_query"):
        return JsonResponse({"error": "Permission denied"}, status=403)

    payload = _extract_payload(request)
    query_name = str(payload.get("name") or "").strip()
    query_sql = str(payload.get("query") or "").strip()
    query_id = payload.get("id")

    if not query_name:
        return JsonResponse({"error": "Query name is required"}, status=400)

    if not query_sql:
        return JsonResponse({"error": "Query text is required"}, status=400)

    if query_id:
        sql_query = SqlQuery.objects.filter(id=query_id, created_by=request.user).first()
        if not sql_query:
            return JsonResponse({"error": "Query not found"}, status=404)

        sql_query.name = query_name
        sql_query.query = query_sql
        sql_query.updated_by = request.user
        sql_query.save(update_fields=["name", "query", "updated_by", "datetime_updated"])
    else:
        sql_query = SqlQuery.objects.create(
            name=query_name,
            query=query_sql,
            created_by=request.user,
            updated_by=request.user,
        )

    return JsonResponse(
        {
            "query": {
                "id": sql_query.id,
                "name": sql_query.name,
                "query": sql_query.query,
            }
        }
    )


def _extract_payload(request: HttpRequest) -> dict:
    content_type = request.headers.get("Content-Type", "")

    if "application/json" in content_type:
        try:
            body = request.body.decode("utf-8")
            return json.loads(body) if body else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    return {
        "id": request.POST.get("id"),
        "name": request.POST.get("name"),
        "query": request.POST.get("query"),
    }
