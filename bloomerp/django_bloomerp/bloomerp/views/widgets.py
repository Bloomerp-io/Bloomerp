from django.contrib.auth.mixins import PermissionRequiredMixin
from formtools.wizard.views import SessionWizardView
from django.shortcuts import redirect
from bloomerp.forms.widgets import WidgetForm1, WidgetForm2, WidgetForm3
from bloomerp.models import Widget, SqlQuery, ApplicationField
from bloomerp.utils.router import BloomerpRouter
from bloomerp.views.mixins import HtmxMixin, BloomerpModelFormViewMixin, BloomerpModelContextMixin
from bloomerp.views.core import BloomerpBaseDetailView
from django.views.generic.edit import CreateView, UpdateView
from django.views.generic.detail import DetailView
from bloomerp.components.workspaces.workspace_widget import workspace_widget


router = BloomerpRouter()

# ---------------------------------
# Sql Query Create View
# ---------------------------------
@router.bloomerp_route(
    models = SqlQuery,
    path='create',
    name= 'Create Sql Query',
    description='Create a new Sql Query',
    route_type='list',
    url_name='add'
)
class SqlQueryCreateView(PermissionRequiredMixin, HtmxMixin, BloomerpModelFormViewMixin, CreateView):
    model = SqlQuery
    template_name = 'widget_views/base_sql_query_builder_view.html'
    permission_required = ['widget.add_widget']
    fields = ['name', 'query']
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['model'] = self.model
        context['db_tables_and_columns'] = ApplicationField.get_db_tables_and_columns()
        return context
    
# ---------------------------------
# Sql Query Editor View
# ---------------------------------
@router.bloomerp_route(
    models = SqlQuery,
    path='editor',
    name= 'Sql Query Editor',
    description='Edit a Sql Query',
    route_type='detail',
    url_name='editor'
)
class SqlQueryEditorView(PermissionRequiredMixin, BloomerpModelContextMixin, HtmxMixin, BloomerpModelFormViewMixin, UpdateView):
    model = SqlQuery
    template_name = "widget_views/snippets/sql_query_builder_snippet.html"
    permission_required = ['bloomerp.execute_sql_query']
    fields = ['name', 'query']
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['model'] = self.model
        context['db_tables_and_columns'] = ApplicationField.get_db_tables_and_columns()
        return context

    def get_object(self, queryset=None):
        return self.model.objects.get(pk=self.kwargs.get('pk'))

    def get_success_url(self):
        return self.object.get_absolute_url()

    





# ---------------------------------
# Widget Create Wizard View
# ---------------------------------
@router.bloomerp_route(
        models=Widget,
        path='create',
        name='Create Widget',
        description='Create a new Widget',
        route_type='list',
        url_name='add'
)
class WidgetCreateWizardView(PermissionRequiredMixin, HtmxMixin, SessionWizardView):
    form_list = [WidgetForm1, WidgetForm2, WidgetForm3]
    template_name = 'create_views/bloomerp_base_wizard_create_view.html'
    permission_required = 'shared_utils.add_widget'
    model = None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['model_name_plural'] = 'Widgets'
        context['model_name'] = 'Widget'
        context['model'] = self.model
        return context

    def get_form_kwargs(self, step=None):
        """
        Returns the keyword arguments for instantiating the form
        (or formset) on the given step.
        """
        if step == '2':
            # Fetch the output type selected in the previous step
            output_type = self.get_cleaned_data_for_step('1')['output_type']

            # Fetch the query selected in the first step
            query = self.get_cleaned_data_for_step('0')['query']

            return {'output_type': output_type, 'query': query}

        return {}

    def done(self, form_list, **kwargs):
        form_data = [form.cleaned_data for form in form_list]
        
        # Extract the form data
        name = form_data[0]['name']
        description = form_data[0]['description']
        query = form_data[0]['query']
        output_type = form_data[1]['output_type']
        options = {key: value for form in form_data[2:] for key, value in form.items()}

        if options.get('group_by') == '':
            del options['group_by'] 

        # Create Widget instance
        widget = Widget(
            name=name,
            description=description,
            query=query,
            output_type=output_type,
            options=options,
            created_by=self.request.user,
            updated_by=self.request.user
        )

        widget.save()

        return redirect(widget.get_absolute_url())  # Redirect to a new URL


@router.bloomerp_route(
    models=Widget,
    path='preview',
    name='Preview Widget',
    description='Preview a widget',
    route_type='detail',
    url_name='preview'
)
class WidgetPreviewView(BloomerpModelContextMixin, HtmxMixin, DetailView):
    model = Widget
    template_name = 'components/workspace_widget.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['widget'] = self.object
        return context
    
    def get(self, request, *args, **kwargs):
        # Call the components_workspace_widget view with the widget_id GET parameter
        request.GET = request.GET.copy()
        request.GET['widget_id'] = kwargs.get('pk')
        return workspace_widget(request)


@router.bloomerp_route(
    models=Widget,
    path='update/',
    name='Update',
    description='Update widget',
    route_type='detail',
    url_name='update'
)
class WidgetUpdateWizardView(PermissionRequiredMixin, SessionWizardView, BloomerpBaseDetailView):
    form_list = [WidgetForm1, WidgetForm2, WidgetForm3]
    template_name = 'detail_views/bloomerp_detail_wizard_update_view.html'
    permission_required = 'shared_utils.change_widget'
    model = Widget  

    
    def get_context_data(self, **kwargs) -> dict:
        context = super().get_context_data(**kwargs)
        context["exclude_header"] = self.exclude_header
        self.object = self.get_object()
        # This is necessary to get the context data from the BloomerpModelContextMixin
        # Don't ask me why, I don't know
        context.update(BloomerpModelContextMixin.get_context_data(self, **kwargs))

        return context

    def get_form_kwargs(self, step=None):
        """
        Returns the keyword arguments for instantiating the form
        (or formset) on the given step.
        """
        if step == '0':
            return {'widget': self.get_object()}

        if step == '1':
            return {'widget': self.get_object()}

        if step == '2':
            # Fetch the output type selected in the previous step
            output_type = self.get_cleaned_data_for_step('1')['output_type']

            # Fetch the query selected in the first step
            query = self.get_cleaned_data_for_step('0')['query']

            return {'output_type': output_type, 'query': query, 'widget': self.get_object()}

        return {}

    def done(self, form_list, **kwargs):
        form_data = [form.cleaned_data for form in form_list]
        
        # Extract the form data
        name = form_data[0]['name']
        description = form_data[0]['description']
        query = form_data[0]['query']
        output_type = form_data[1]['output_type']
        options = {key: value for form in form_data[2:] for key, value in form.items()}

        if options.get('group_by') == '':
            del options['group_by'] 

        # Get the object
        widget : Widget = self.get_object()

        widget.name = name
        widget.description = description
        widget.query = query
        widget.output_type = output_type
        widget.options = options
        widget.updated_by = self.request.user
        widget.created_by = self.request.user
        
        widget.save()
        return redirect(widget.get_absolute_url())

