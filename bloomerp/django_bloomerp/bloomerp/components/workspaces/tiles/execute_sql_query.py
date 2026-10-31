from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, render

from bloomerp.models.workspaces.sql_query import SqlQuery
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router
from bloomerp.services.sql_services import SqlExecutor


def _parse_positive_int(value: str | None, default: int) -> int:
    """Parse a positive pagination value, falling back for invalid input."""
    try:
        parsed = int(value or "")
    except (TypeError, ValueError):
        return default

    return parsed if parsed > 0 else default


@router.register(path='components/execute_sql_query/', name='components_execute_sql_query')
@login_required
def execute_sql_query(request:HttpRequest) -> HttpResponse:
    """Render results for posted SQL or an authorized saved query loaded into a modal."""
    if request.method not in {"GET", "POST"}:
        return HttpResponseNotAllowed(["GET", "POST"])

    if not request.user.has_perm("bloomerp.execute_sql_query"):
        return HttpResponse("Permission denied", status=403)

    if request.method == "GET":
        try:
            query_id = UUID(request.GET.get("query_id", ""))
        except ValueError:
            return HttpResponse("Invalid SQL query ID", status=400)
        saved_query = get_object_or_404(SqlQuery, pk=query_id)
        if not UserPolicyManager(request.user).has_access_to_object(
            saved_query, BloomerpPermission.VIEW, fields=["query"]
        ):
            return HttpResponse("Permission denied", status=403)
        query = saved_query.query.strip()
        parameters = request.GET
    else:
        query = (request.POST.get("sql_query") or "").strip()
        parameters = request.POST
    if not query:
        return HttpResponse("No SQL query provided", status=400)

    page = _parse_positive_int(parameters.get("sql_page"), default=1)
    page_size = _parse_positive_int(parameters.get("sql_page_size"), default=25)

    executor = SqlExecutor(request.user)

    try:
        result = executor.execute_query(query, page=page, page_size=page_size)
    except PermissionError as error:
        return render(
            request,
            "components/workspaces/tiles/execute_sql_query.html",
            {
                "error_message": str(error),
            },
            status=403,
        )
    except ValueError as error:
        return render(
            request,
            "components/workspaces/tiles/execute_sql_query.html",
            {
                "error_message": str(error),
            },
            status=400,
        )
    except Exception as error:
        return render(
            request,
            "components/workspaces/tiles/execute_sql_query.html",
            {
                "error_message": f"Query execution failed: {error}",
            },
            status=500,
        )

    context = {
        "columns": result.columns,
        "rows": result.rows,
        "row_count": result.row_count,
        "page_rows_count": result.page_rows_count,
        "execution_ms": result.execution_ms,
        "policy_message": result.policy_message,
        "page": result.page,
        "page_size": result.page_size,
        "total_pages": result.total_pages,
        "page_start": result.page_start,
        "page_end": result.page_end,
    }
    return render(request, 'components/workspaces/tiles/execute_sql_query.html', context)
