from bloomerp.utils.router import route
from django.shortcuts import render
from django.http import HttpResponse, HttpRequest
from django.shortcuts import get_object_or_404
from bloomerp.models import Widget
import plotly.express as px
from django.contrib.auth.decorators import login_required
from django.core.cache import cache

@login_required
@route('workspace_widget')
def workspace_widget(request:HttpRequest) -> HttpResponse:
    '''
    Component to render a widget in the workspace.

    GET Parameters:
    - widget_id: The ID of the widget to render
    - download: If set to xlsx or csv, the component will return a download response
    '''
    # Permission check
    if not request.user.has_perm('bloomerp.view_workspace'):
        return HttpResponse(
            'User does not have permission to view widgets'
        )


    # Get the KPI ID
    widget_id = request.GET.get('widget_id')
    if not widget_id:
        return HttpResponse('Widget ID is required', status=400)
    
    # Check if the a refresh is requested
    # Refresh yet to be implemented 
    refresh = request.GET.get('refresh', False)
    if refresh:
        cache.delete(f'widget_{widget_id}')


    # Check cache
    cache_key = f'widget_{widget_id}'
    cached_response = cache.get(cache_key)
    if cached_response:
        return cached_response

    # Get download
    download = request.GET.get('download', False)

    # Get the KPI object
    widget = get_object_or_404(Widget, pk=widget_id)

    # Get the data
    x = widget.options.get('x')
    y = widget.options.get('y')
    group_by = widget.options.get('group_by')
    data = widget.query.executor.execute_to_df(
        query=widget.query.query,
        safe=True,
        use_cache=True
    )


    #--------------------------------
    # Download
    #--------------------------------
    if download == 'xlsx':
        response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = f'attachment; filename="{widget.name}.xlsx"'
        data.to_excel(response, index=False)
        return response
    elif download == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{widget.name}.csv"'
        data.to_csv(response, index=False)
        return response

    #--------------------------------
    # Output to HTML
    #--------------------------------

    if widget.output_type == 'value':
        result = data.iloc[0, 0]
    elif widget.output_type == 'bar':
        fig = px.bar(data, x=x, y=y, color=group_by, height=300)
        result = fig.to_html(full_html=False)
    elif widget.output_type == 'line':
        fig = px.line(data, x=x, y=y, color=group_by, height=300)
        result = fig.to_html(full_html=False)
    elif widget.output_type == 'pie':
        fig = px.pie(data, names=group_by, values=x, height=300)
        result = fig.to_html(full_html=False)
    elif widget.output_type == 'scatter':
        fig = px.scatter(data, x=x, y=y, color=group_by, height=300)
        result = fig.to_html(full_html=False)
    elif widget.output_type == 'histogram':
        fig = px.histogram(data, x=x, color=group_by, height=300)
        result = fig.to_html(full_html=False)

    elif widget.output_type == 'table':
        columns = widget.options.get('columns')
        limit = widget.options.get('limit')
        data = data[columns].iloc[:limit].values.tolist()
        result = {
            'columns': columns,
            'data': data
        }

    # Add context
    context = {
        'widget': widget,
        'result': result
    }
    
    response = render(request, 'components/workspace_widget.html', context)
    
    # Set cache
    cache.set(cache_key, response, timeout=60*15)  # Cache for 15 minutes
    
    return response