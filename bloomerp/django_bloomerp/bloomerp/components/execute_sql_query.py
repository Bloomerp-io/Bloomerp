from bloomerp.router import router
from django.shortcuts import render
from django.http import HttpResponse, HttpRequest
from django.contrib.auth.decorators import login_required

from bloomerp.services.sql_services import SqlExecutor


@router.register(path='components/execute_sql_query/', name='components_execute_sql_query')
@login_required
def execute_sql_query(request:HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    if not request.user.has_perm("bloomerp.execute_sql_query"):
        return HttpResponse("Permission denied", status=403)

    query = (request.POST.get("sql_query") or "").strip()
    if not query:
        return HttpResponse("No SQL query provided", status=400)

    executor = SqlExecutor(request.user)

    try:
        result = executor.execute_query(query)
    except PermissionError as error:
        return render(
            request,
            "components/execute_sql_query.html",
            {
                "error_message": str(error),
            },
            status=403,
        )
    except ValueError as error:
        return render(
            request,
            "components/execute_sql_query.html",
            {
                "error_message": str(error),
            },
            status=400,
        )
    except Exception as error:
        return render(
            request,
            "components/execute_sql_query.html",
            {
                "error_message": f"Query execution failed: {error}",
            },
            status=500,
        )

    context = {
        "columns": result["columns"],
        "rows": result["rows"],
        "row_count": result["row_count"],
        "execution_ms": result["execution_ms"],
        "policy_message": result["policy_message"],
    }
    return render(request, 'components/execute_sql_query.html', context)