from typing import Any
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseRedirect,
)
from django.shortcuts import render
from django.urls import reverse
from django.views.generic.detail import DetailView
from django.views.generic.edit import UpdateView, CreateView
from django.views.generic.list import ListView
from django.views.generic import View
from django.contrib.auth.mixins import PermissionRequiredMixin, LoginRequiredMixin
from django.contrib.contenttypes.models import ContentType
from bloomerp.models import (
    ApplicationField,
    File,
    Widget,
    SqlQuery,
    UserDetailViewPreference,
    Bookmark
)
from bloomerp.forms.core import BloomerpDownloadBulkUploadTemplateForm
from django.contrib import messages
from django.contrib.messages.views import SuccessMessageMixin
from bloomerp.utils.models import model_name_plural_underline, get_list_view_url, get_detail_view_url
from django.db.models import Model
from bloomerp.views.mixins import (
    BloomerpModelFormViewMixin,
    BloomerpModelContextMixin,
    HtmxMixin
)

from shared_utils.router.view_router import BloomerpRouter, _get_name_or_slug
from django.forms.models import modelform_factory
from bloomerp.forms.core import BloomerpModelForm
from django import forms
from django.contrib.auth import get_user_model
User = get_user_model()


router = BloomerpRouter()

# ---------------------------------
# Bloomerp List View
# ---------------------------------
@router.bloomerp_route(
    path="list",
    name="{model} list",
    url_name="list",
    description="List of {model} model",
    route_type="list",
    exclude_models=[File]
)
class BloomerpListView(PermissionRequiredMixin, BloomerpModelContextMixin, HtmxMixin, ListView):
    model : Model = None # The model to use for the view
    template_name : str = "list_views/bloomerp_list_view.html" # The template to use for rendering the view
    context_object_name : str = "object_list" # The name of the context variable to use in the template
    create_object_url : str = None
    permission_required = None

    def get_permission_required(self):
        if self.permission_required:
            return self.permission_required
        else:
            return [f"{self.model._meta.app_label}.view_{self.model._meta.model_name}"]
        
    def get_context_data(self, **kwargs: Any) -> dict:
        context = super().get_context_data(**kwargs)
        context["title"] = self.model._meta.verbose_name.capitalize() + " list"
        return context

    
# ---------------------------------
# Bloomerp Detail View
# ---------------------------------
class BloomerpBaseDetailView(HtmxMixin, BloomerpModelContextMixin, DetailView):
    htmx_template = 'bloomerp_htmx_base_view.html'
    tabs = None
    exclude_header = False

    def get_context_data(self, **kwargs: Any) -> dict:
        context = super().get_context_data(**kwargs)
        context["exclude_header"] = self.exclude_header

        if self.tabs:
            context["tabs"] = self.tabs

        return context

# ---------------------------------
# Bloomerp Detail Overview View
# ---------------------------------
@router.bloomerp_route(
    path="",
    name="Overview",
    url_name="overview",
    description="Overview of object from {model} model",
    route_type="detail",
    models = "__all__",
)
class BloomerpDetailOverviewView(PermissionRequiredMixin, BloomerpBaseDetailView):
    template_name = "detail_views/bloomerp_detail_overview_view.html"
    settings = None
    
    def get_permission_required(self):
        return [f"{self.model._meta.app_label}.view_{self.model._meta.model_name}"]

    def get_context_data(self, **kwargs: Any) -> dict:
        context = super().get_context_data(**kwargs)

        content_type = ContentType.objects.get_for_model(self.model)

        queryset = UserDetailViewPreference.objects.filter(
            user=self.request.user, application_field__content_type=content_type
        )

        # Add content type id to context
        context["view_type"] = "DETAIL"
        context["content_type_id"] = content_type.pk
        if not queryset:
            queryset = UserDetailViewPreference.generate_default_for_user(
                user = self.request.user,
                content_type = content_type
            )
            
        left_column = queryset.filter(position="LEFT")
        center_column = queryset.filter(position="CENTER")
        right_column = queryset.filter(position="RIGHT")

        # Do some processing
        i = 0
        if left_column:
            i += 1
        if center_column:
            i += 1
        if right_column:
            i += 1

        if i == 0:
            col_span = 12
        else:
            col_span = 12 / i

        context["col_span"] = int(col_span)
        context["left_column"] = left_column
        context["right_column"] = right_column
        context["center_column"] = center_column

        return context

# ---------------------------------
# Bloomerp Create View
# ---------------------------------
@router.bloomerp_route(
    path="create",
    name="Create {model}",
    url_name="add",
    description="Create a new object from {model}",
    route_type="list",
    exclude_models=[File, Widget, SqlQuery, User]
)
class BloomerpCreateView(
        PermissionRequiredMixin, 
        SuccessMessageMixin,
        HtmxMixin, 
        BloomerpModelFormViewMixin,
        CreateView):
    template_name = "create_views/bloomerp_create_view.html"
    fields = None
    exclude = []
    success_message = "Object was created successfully."

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["model_name"] = self.model._meta.verbose_name
        context["model_name_plural"] = self.model._meta.verbose_name_plural
        context["list_view_url"] = model_name_plural_underline(self.model) + "_list"
        context["model"] = self.model
        context["title"] = 'Create ' + self.model._meta.verbose_name
        return context

    def get_permission_required(self):
        return [f"{self.model._meta.app_label}.add_{self.model._meta.model_name}"]

    def get_success_message(self, cleaned_data):
        return f"{self.object} was created successfully."
    
    def get_success_url(self):
        try:
            return self.object.get_absolute_url()
        except AttributeError:
            return reverse(get_detail_view_url(self.object), kwargs={"pk": self.object.pk})

# ---------------------------------
# Bloomerp Update View
# ---------------------------------
@router.bloomerp_route(
    path="update",
    name="Update",
    url_name="update",
    description="Update object from {model}",
    route_type="detail",
    exclude_models=[File, Widget]
)
class BloomerpUpdateView(
        PermissionRequiredMixin, 
        SuccessMessageMixin, 
        HtmxMixin,
        BloomerpModelFormViewMixin,
        BloomerpModelContextMixin,
        UpdateView
        ):
    template_name = "detail_views/bloomerp_detail_update_view.html"
    settings = None
    _uses_base_form = False

    def get_success_url(self):
        try:
            return self.object.get_absolute_url()
        except AttributeError:
            return reverse(get_detail_view_url(self.object), kwargs={"pk": self.object.pk})


    def get_permissions(self):
        """
        Returns a dictionary of standard add, change, delete, and view permissions
        for the given model.

        Returns:
        Dictionary with keys 'add', 'change', 'delete', 'view' and their corresponding
        permission codenames as values.
        """
        model_name = self.model._meta.model_name  # Get the model name in lowercase
        app_label = self.model._meta.app_label  # Get the app label

        permissions = {
            "create": f"{app_label}.add_{model_name}",
            "update": f"{app_label}.change_{model_name}",
            "delete": f"{app_label}.delete_{model_name}",
            "read": f"{app_label}.view_{model_name}",
        }

        return permissions

    def get_permission_required(self):
        return [self.get_permissions()["update"]]

    def post(self, request: HttpRequest, *args: str, **kwargs: Any) -> HttpResponse:
        if request.POST.get("delete"):
            if not request.user.has_perm(self.get_permissions()["delete"]):
                messages.error(
                    request,
                    f'User does not have the required permission: {self.get_permissions()["delete"]}.',
                )
                return HttpResponseRedirect(request.path)

            self.get_object().delete()
            messages.info(request, f"Object was deleted successfully.")
            
            url = get_list_view_url(self.model)

            return HttpResponseRedirect(reverse(url))

        return super().post(request, *args, **kwargs)

    def get_success_message(self, cleaned_data):
        return f"{self.object} was updated successfully."

# ---------------------------------
# Bloomerp many-to-many detail view
# ---------------------------------
from django.db.models.fields.reverse_related import ManyToManyRel, ManyToOneRel
from bloomerp.models import Comment
def get_view_parameters(model:Model):
    params_list = []
    model_name = model._meta.verbose_name

    fields = model._meta.get_fields()

    if model in [File, Comment]:
        return False

    for field in fields:
        # Skip fields that 
        if field.name in ['created_by','updated_by']:
            continue

        if field.get_internal_type() == 'ManyToManyField':
            if field.related_model in [Comment, File]:
                continue

            if type(field) == ManyToManyRel:
                params_dict = {
                    'path' : f'{_get_name_or_slug(field.related_model, slug=True)}',
                    'name' : f'{field.related_model._meta.verbose_name_plural.capitalize()}',
                    'url_name' : f'{_get_name_or_slug(field.related_model)}_relationship',
                    'model' : model,
                    'route_type' : 'detail',
                    'description' : f'{field.related_model._meta.verbose_name_plural.capitalize()} relationship for {model_name}',
                    'args': {
                        'related_model':field.related_model,
                        'related_model_attribute' : field.name,
                        'reversed':True,
                        'related_model_field' : field.remote_field.name
                    }
                }
                
            else:
                if field.related_model in [Comment, File]:
                    continue

                params_dict = {
                    'path' : f'{field.name}/',
                    'name' : f'{field.verbose_name.capitalize()}',
                    'url_name' : field.name + '_relationship',
                    'description' : f'{field.verbose_name.capitalize()} relationship for {model_name}',
                    'model' : model,
                    'route_type' : 'detail',
                    'args' : {
                        'related_model':field.related_model,
                        'related_model_attribute':True,
                        'reversed':False,
                        'related_model_field':field.remote_field.name
                        }
                }

            params_list.append(params_dict)

        elif type(field) == ManyToOneRel:
            if field.related_model in [Comment, File]:
                return False

            params_dict = {
                'path' : f'{_get_name_or_slug(field.related_model, slug=True)}',
                'name' : f'{field.name.capitalize().replace('_',' ')}',
                'url_name' : f'{_get_name_or_slug(field.related_model)}_relationship',
                'model' : model,
                'route_type' : 'detail',
                'description' : f'{field.name.capitalize().replace('_',' ')} relationship for {model_name}',
                'args': {
                    'related_model':field.related_model,
                    'related_model_attribute' : field.name,
                    'reversed':False,
                    'related_model_field' : field.remote_field.name
                }
            }
        
            params_list.append(params_dict)

    return params_list


@router.bloomerp_route(from_func=get_view_parameters)
class BloomerpDetailM2MView(
        PermissionRequiredMixin,
        BloomerpBaseDetailView
        ):
    template_name : str = "detail_views/bloomerp_detail_m2m_view.html"
    model : Model = None
    related_model : Model = None
    related_model_attribute : str = None
    reversed : bool = None
    related_model_field : str = None

    def get_permission_required(self):
        foreign_view_permission = f"{self.related_model._meta.app_label}.view_{self.related_model._meta.model_name}"
        model_view_permission = (
            f"{self.model._meta.app_label}.view_{self.model._meta.model_name}"
        )
        return [foreign_view_permission, model_view_permission]

    def get_context_data(self, **kwargs: Any) -> dict:
        context = super().get_context_data(**kwargs)
        
        # Construct initial query
        initial_query = f'{self.related_model_field}={self.get_object().pk}'        

        # Get application fields for the foreign model
        application_fields = ApplicationField.get_for_model(self.related_model)
        if self.reversed == False:
            # Create form
            Form = modelform_factory(model=self.related_model, fields='__all__', form=BloomerpModelForm)
            
            form = Form(model=self.related_model, user=self.request.user, initial={self.related_model_field:self.get_object().pk})

            context['form'] = form

        # Set content_type_id 
        context['foreign_content_type_id'] = ContentType.objects.get_for_model(self.related_model).pk
        context['foreign_model_attribute'] = self.related_model_attribute
        context['object'] = self.object
        context['application_fields'] = application_fields
        context['initial_query'] = initial_query
        context['reversed'] = self.reversed
        context['related_model'] = self.related_model
        context['related_model_name_singular'] = self.related_model._meta.verbose_name
        context['related_model_name_plural'] = self.related_model._meta.verbose_name_plural
        return context


# ---------------------------------
# Bloomerp Detail File View
# ---------------------------------
@router.bloomerp_route(
    path="files",
    name="Files",
    url_name="files",
    description="Files for object for {model} model",
    route_type="detail",
    exclude_models=[File]
)
class BloomerpDetailFileListView(PermissionRequiredMixin, BloomerpBaseDetailView):
    template_name = "snippets/files_snippet.html"
    
    def get_permission_required(self):
        return [f"{self.model._meta.app_label}.view_{self.model._meta.model_name}"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        fields = ['name', 'datetime_created', 'datetime_updated', 'created_by','updated_by', 'object_id', 'content_type']
        
        context['files_application_fields'] = ApplicationField.objects.filter(content_type=ContentType.objects.get_for_model(File), field__in=fields)
        context['title'] = f'Files for {self.get_object()}'
        context['target'] = 'file_results'
        return context

# ---------------------------------
# Bloomerp Bulk Upload View
# ---------------------------------
@router.bloomerp_route(
    path="bulk-upload",
    name="Bulk Upload {model}",
    url_name="bulk_upload",
    description="Bulk upload objects from {model}",
    route_type="list",
    exclude_models=[File]
)
class BloomerpBulkUploadView(PermissionRequiredMixin, HtmxMixin, View):
    template_name = "list_views/bloomerp_bulk_upload_view.html"
    model = None
    success_url = None
    success_message = "Objects were uploaded successfully."
    
    def get_permission_required(self):
        # Probably want to add a bulk upload permission here
        return [f"{self.model._meta.app_label}.bulk_add_{self.model._meta.model_name}"]

    def get_context_data(self, **kwargs) -> dict:
        context = super().get_context_data(**kwargs)
        context["model_name"] = self.model._meta.verbose_name
        context["model"] = self.model
        context["title"] = f'Bulk upload {self.model._meta.verbose_name_plural}'
        context["model_name_plural"] = self.model._meta.verbose_name_plural
        context["content_type_id"] = ContentType.objects.get_for_model(self.model).pk
        context["list_view_url"] = model_name_plural_underline(self.model) + "_list"
        context["fields_form"] = BloomerpDownloadBulkUploadTemplateForm(self.model)
        return context

    def get(self, request, *args, **kwargs):
        context = self.get_context_data()
        return render(request, self.template_name, context)


# ---------------------------------
# Bloomerp File List View
# ---------------------------------
@router.bloomerp_route(
    path="list",
    name="Files",
    url_name="list",
    description="Bloomerp Files",
    route_type="list",
    models = [File]
)
class BloomerpFileListView(PermissionRequiredMixin, HtmxMixin, View):
    template_name = "list_views/bloomerp_file_list_view.html"
    model = File

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Get the application fields for filter purposes
        fields = ['name', 'datetime_created', 'datetime_updated', 'created_by','updated_by', 'object_id', 'content_type']
        context['target'] = 'file_list'
        context['application_fields'] = ApplicationField.objects.filter(content_type=ContentType.objects.get_for_model(self.model), field__in=fields)
        return context

    def get_permission_required(self):
        return [f"{self.model._meta.app_label}.view_{self.model._meta.model_name}"]
    
    def get(self, request, *args, **kwargs):
        context = self.get_context_data()

        return render(request, self.template_name, context)
    
# ---------------------------------
# Bloomerp Detail Comments View
# ---------------------------------
from bloomerp.models import Comment
@router.bloomerp_route(
    path="comments",
    name="Comments",
    url_name="{model}_detail_comments",
    description="Comments for object from {model} model",
    route_type="detail",
    models="__all__"
)
class BloomerpDetailCommentsView(PermissionRequiredMixin, BloomerpBaseDetailView):
    template_name = "detail_views/bloomerp_detail_comments_view.html"
    model = None

    def get_permission_required(self):
        return [f"{self.model._meta.app_label}.view_{self.model._meta.model_name}"]
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if not hasattr(self.object, 'comments'):
            comments = Comment.objects.filter(content_type=self.content_type, object_id=self.object.pk)
        else:
            comments = self.object.comments.all()

        context['comments'] = comments
        return context

# ---------------------------------
# Bloomerp Bookmarks View
# ---------------------------------
@router.bloomerp_route(
    path="user-bookmarks",
    name="Bookmarks for user",
    url_name="user_bookmarks",
    description="Bookmarks for user",
    route_type="list",
    models=[Bookmark]
)
class BloomerpBookmarksView(LoginRequiredMixin, HtmxMixin, View):
    template_name = "list_views/bloomerp_bookmarks_view.html"
    model = None

    def get_permission_required(self):
        return [f"{self.model._meta.app_label}.view_{self.model._meta.model_name}"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['content_type_id'] = ContentType.objects.get_for_model(self.model).pk
        context['initial_query'] = 'user=' + str(self.request.user.pk)
        return context

    def get(self, request, *args, **kwargs):
        context = self.get_context_data()
        return render(request, self.template_name, context)




'''
from formtools.wizard.views import SessionWizardView
from collections import OrderedDict
from django import forms
from modules.documents.forms import generate_fields_for_model_document_templates
from django.core.files.storage import FileSystemStorage
import os
from django.conf import settings
class BaseWizzardCreateView(
    PermissionRequiredMixin, SuccessMessageMixin, SessionWizardView
):
    template_name = "bloomerp_base_wizard_create_view.html"
    model = None
    fields = None
    exclude = []
    success_message = "Object was created successfully."
    form_list = [BaseProjectModelForm]
    permission_required = None
    file_storage = FileSystemStorage(
        location=os.path.join(settings.MEDIA_ROOT, "temporary")
    )
    model_form = None
    document_generator = True

    def get_permission_required(self):
        if self.permission_required:
            return self.permission_required
        else:
            return [f"{self.model._meta.app_label}.add_{self.model._meta.model_name}"]

    def get_context_data(self, form, **kwargs):
        context = super().get_context_data(form, **kwargs)
        context["model_name"] = self.model._meta.verbose_name
        return context

    def get_form_kwargs(self, step=None):
        kwargs = super().get_form_kwargs(step)

        if step == "last":
            return kwargs

        kwargs["user"] = self.request.user

        return kwargs

    def get_form_list(self):
        # Create a form list with the model form
        form_list = OrderedDict()

        # Check if a model form is provided
        if self.model_form:
            Form = self.model_form
        else: 
            Form = modelform_factory(
                model=self.model,
                fields="__all__",
                form=BaseProjectModelForm,
                exclude=self.exclude + ["last_updated_by"],
            )

        form_list["0"] = None

        # Check if model already has any items in the database to avoid RelatedObjectDoesNotExist error, if not, skip the foreign relationships
        # This error only occurs when a foreing relationship is mandatory
        # This is a workaround to avoid the error
        has_items = self.model.objects.first()

        # Get related models
        qs = ApplicationField.get_related_models(self.model, skip_auto_created=False)
        qs = qs.exclude(field_type="OneToManyField").exclude(
            field_type="ManyToManyField"
        )

        self.application_fields = qs

        for i, application_field in enumerate(qs):
            # Get the model from the application field
            model = application_field.content_type.model_class()

            # Check if model has any items in the database
            if model.objects.exists():
                ForeignForm = modelform_factory(
                    model=model, fields="__all__", form=BaseProjectModelForm
                )
                # Hide the foreign key field

                ForeignForm.base_fields[
                    application_field.field
                ].widget = forms.HiddenInput()

                form_list[str(i + 1)] = ForeignForm

                Form.base_fields[f"add_{model._meta.model_name}"] = forms.BooleanField(
                    label=f"Add {model._meta.verbose_name}", required=False
                )

                # Create lambda function to set conditional form
                conditional_function = lambda wizard, model=model: (
                    wizard.get_cleaned_data_for_step("0") or {}
                ).get(f"add_{model._meta.model_name}")
                self.condition_dict[str(i + 1)] = conditional_function

        # Add conditional form to generate documents
        Form.base_fields["generate_documents"] = forms.BooleanField(
            label="Generate documents", required=False
        )
        self.condition_dict["last"] = lambda wizard: (
            wizard.get_cleaned_data_for_step("0") or {}
        ).get("generate_documents")
        fields = generate_fields_for_model_document_templates(
            self.model, only_standard_documents=True
        )

        if self.document_generator:
            DocumentTemplateForm = forms.Form
            for field in fields:
                DocumentTemplateForm.base_fields[field[0]] = field[1]

            form_list["last"] = DocumentTemplateForm
        form_list["0"] = Form

        self.form_list = form_list

        return super().get_form_list()

    def get_form_initial(self, step):
        """Sets the initial foreign relationships"""
        initial = super().get_form_initial(step)

        for i, application_field in enumerate(self.application_fields):
            # Set the initial value for the foreign relationship form to a random object
            random_object = self.model.objects.first()
            initial[application_field.field] = random_object

        return initial

    def done(self, form_list, form_dict, **kwargs):
        # Create the main object
        main_obj = form_dict["0"].save(commit=False)

        # Set the last_updated_by attribute if it exists
        if hasattr(main_obj, "last_updated_by"):
            main_obj.last_updated_by = self.request.user

        # Save the main object
        main_obj.save()

        # Save many-to-many relationships if needed
        if hasattr(form_dict["0"], "save_m2m"):
            form_dict["0"].save_m2m()

        if hasattr(form_dict["0"], "update_file_fields"):
            form_dict["0"].update_file_fields()

        # Create the foreign relationships
        for i, application_field in enumerate(self.application_fields):
            if form_dict.get(str(i + 1)):
                foreign_obj = form_dict[str(i + 1)].save(commit=False)
                setattr(foreign_obj, application_field.field, main_obj)
                foreign_obj.save()

        # Generate documents from document templates
        templates = DocumentTemplate.get_standard_documents_for_instance(main_obj)
        if form_dict.get("last"):
            free_variables = form_dict["last"].cleaned_data
            controller = DocumentController()

            for template in templates:
                try:
                    controller.create_document(template, main_obj, free_variables)
                except Exception as e:
                    messages.error(
                        self.request, f"Error generating document {template.name}: {e}"
                    )

        return redirect(main_obj.get_absolute_url())

    def get_success_message(self, cleaned_data):
        return f"{self.object} was created successfully."

'''