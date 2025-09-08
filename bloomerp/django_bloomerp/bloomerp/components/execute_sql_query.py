from bloomerp.utils.router import route
from django.shortcuts import render
from django.http import HttpResponse, HttpRequest
from bloomerp.utils.sql import SqlQueryExecutor # For some reason if I import utils.sql, the router doesn't work
from django.contrib.auth.decorators import login_required

@login_required
@route('execute_sql_query')
def execute_sql_query(request:HttpRequest) -> HttpResponse:
    '''
    Executes a SQL query and returns the result in a html table.
    '''
    # Permission check
    if not request.user.has_perm('bloomerp.execute_sql_query'):
        return HttpResponse('User does not have permission to execute SQL queries')

    query = request.GET.get('sql_query')

    if not query:
        return HttpResponse('No SQL Query provided!')

    executor = SqlQueryExecutor()

    try:
        df = executor.execute_to_df(query)
    except Exception as e:
        return HttpResponse(f'SQL Query error: {e}')
    

    context = {
        "column_names": df.columns.tolist(),
        "data": df.values.tolist()	
    }

    return render(request, 'components/execute_sql_query.html', context)