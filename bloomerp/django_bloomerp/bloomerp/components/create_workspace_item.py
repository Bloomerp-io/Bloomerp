from bloomerp.utils.router import route
from django.shortcuts import render
from django.http import HttpResponse, HttpRequest
from bloomerp.models.fields import TextEditorField
from bloomerp.widgets.foreign_key_widget import ForeignKeyWidget
from bloomerp.widgets.multiple_model_select_widget import MultipleModelSelect
from bloomerp.widgets.text_editor import RichTextEditorWidget
from django.forms.fields import CharField
from django.forms.widgets import Textarea
from bloomerp.models import Link, Widget
import uuid
from django.contrib.auth.decorators import login_required


@login_required
@route('create_workspace_item')
def create_workspace_item(request: HttpRequest) -> HttpResponse:
    # Some permissions check (can user create dashboard item?)
    if not request.user.has_perm('bloomerp.view_workspace'):
        return HttpResponse('Permission denied', status=403)

    # Get the action (get_input, get_snippet)
    action = request.GET.get('action', 'get_input_field')
    if action == 'get_input_field':
        # Get initial data
        item_type = request.GET.get('item_type', 'text')
        if item_type == 'text':
            widget = Textarea()
            field_html = widget.render(name='text', value='', attrs={'class': 'form-control'})
            return HttpResponse(field_html)
        elif item_type == 'header':
            field = CharField()
            field_html = field.widget.render(name='header', value='', attrs={'class': 'form-control'})
            return HttpResponse(field_html)
        elif item_type == 'link':
            field = ForeignKeyWidget(model=Link)
            field_html = field.render(name='link', value=None, attrs={})
            return HttpResponse(field_html)
        elif item_type == 'link_list':
            field = MultipleModelSelect(model=Link)
            field_html = field.render(name='link_list', value=None, attrs={})
            return HttpResponse(field_html)
        elif item_type == 'widget':
            field = ForeignKeyWidget(model=Widget)
            field_html = field.render(name='widget', value=None, attrs={})
            return HttpResponse(field_html)
    elif action == 'get_snippet':
        item = {}
        item['data'] = {}
        item['size'] = 12
        if request.GET.get('text'):
            item['data']['text'] = request.GET.get('text')
            item['type'] = 'text'
        elif request.GET.get('header'):
            item['data']['text'] = request.GET.get('header')
            item['type'] = 'header'
        elif request.GET.get('link'):
            item['data']['link_id'] = request.GET.get('link')
            item['type'] = 'link'
        elif request.GET.get('link_list'):
            item['data']['links'] = request.GET.getlist('link_list')
            item['type'] = 'link_list'
        elif request.GET.get('widget'):
            item['data']['widget_id'] = request.GET.get('widget')
            item['type'] = 'widget'

        item['id'] = uuid.uuid4()
        return render(request, 'snippets/workspace_item.html', {'item': item})
            