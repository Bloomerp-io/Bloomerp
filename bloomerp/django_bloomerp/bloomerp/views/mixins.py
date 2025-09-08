from bloomerp.forms.core import BloomerpModelForm, DetailLinksSelectForm
from django.shortcuts import redirect
from django.http import HttpResponse
from django.forms.models import modelform_factory
from bloomerp.models import ApplicationField, UserDetailViewTab, Link
from django.views.generic import DetailView, UpdateView
from bloomerp.utils.models import (
    get_create_view_url,
    get_update_view_url,
    get_list_view_url,
    get_model_dashboard_view_url,
    get_detail_view_url,
    get_bulk_upload_view_url
)
from django.contrib.contenttypes.models import ContentType
from typing import Any
from django.views.generic.edit import ModelFormMixin


class HtmxMixin:
    '''Updates the template name based on the request.htmx attribute.'''
    htmx_template = 'bloomerp_htmx_base_view.html'
    base_detail_template = 'detail_views/bloomerp_base_detail_view.html'
    htmx_detail_target = 'detail-content'
    htmx_main_target = 'main-content'
    is_detail_view = False

    def get_context_data(self, **kwargs:Any) -> dict:
        try:
            context = super().get_context_data(**kwargs)
        except AttributeError:
            # If the super class does not have a get_context_data method
            context = {}

        # ---------------------
        # NORMAL REQUEST
        # ---------------------
        if not self.request.htmx or self.request.htmx.history_restore_request:
            if self.is_detail_view or isinstance(self, DetailView) or isinstance(self, UpdateView):
                context['include_main_content'] = self.base_detail_template
                context['include_detail_content'] = self.template_name
                context['template_name'] = self.base_detail_template
            else:
                context['template_name'] = self.template_name
            self.template_name = self.htmx_template
        
        # ---------------------
        # HTMX REQUEST
        # ---------------------
        else:
            # Check the target of htmx
            if self.request.htmx.target == self.htmx_main_target:
                if isinstance(self, DetailView) or isinstance(self, UpdateView):
                    # In this case, we are dealing with a detail view
                    context['include_detail_content'] = self.template_name
                    self.template_name = self.base_detail_template
        return context
    
class BloomerpModelFormViewMixin(ModelFormMixin):
    '''
    A mixin that provides a form view for a model.

    It includes the following features:

        - It uses the BloomerpModelForm form class
        - It sets the user and model attributes on the form
        - It saves the form instance to the database
        - It sets the updated_by attribute on the instance if it exists
        - It sets the created_by attribute on the instance if it exists
    '''
    exclude = []
    form_class = BloomerpModelForm

    def get_form_kwargs(self) -> dict:
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        kwargs["model"] = self.model
        return kwargs
    
    def form_valid(self, form: BloomerpModelForm) -> HttpResponse:
        # Call form valid on super class to make sure messages are displayed
        super().form_valid(form)
        
        # Save the form instance but don't commit to the database yet
        obj = form.save(commit=False)

        # Check if the instance has 'last_updated_by' attribute and set it
        if hasattr(obj, "updated_by"):
            obj.updated_by = self.request.user

        # Check if the instance has 'created_by' attribute and set it
        if hasattr(obj, "created_by") and not obj.created_by:
            obj.created_by = self.request.user

        # Now save the object to the database
        obj.save()

        # Check if the form has a save_m2m method and call it
        if hasattr(form, "save_m2m"):
            form.save_m2m()
        
        # Check if the form has an update_file_fields method and call it
        if hasattr(obj, "save_file_fields"):
            obj.save_file_fields()

        return redirect(self.get_success_url())
    
    def get_form(self, form_class=None) -> BloomerpModelForm:
        form = super().get_form(form_class)

        if "updated_by" in form.fields:
            del form.fields["updated_by"]

        if "created_by" in form.fields:
            del form.fields["created_by"]
        
        return form

    def get_form_class(self) -> BloomerpModelForm:
        return modelform_factory(
            model=self.model,
            fields=self.fields,
            form=BloomerpModelForm,
            exclude=self.exclude
        )

from bloomerp.models import BloomerpModel
class BloomerpModelContextMixin:
    '''
    A mixin that provides context data whenever rendering a model view.
    This mixin provides the following context data:
        - user
        - model_name
        - model_name_plural
        - content_type_id
        - model_dashboard_url
        - create_view_url
        - update_view_url
        - list_view_url
        - detail_view_url
        - llm_args

    Note: consider splitting this mixin into list and detail mixins.
    '''
    model: BloomerpModel = None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Check if the model attribute is set
        if not self.model:
            raise NotImplementedError("You must provide a model attribute to the view.")

        # init content type
        content_type = ContentType.objects.get_for_model(self.model)

        self.view_content_type = content_type
        
        # Detail view routes
        detail_view_tabs = UserDetailViewTab.get_detail_view_tabs(content_type=content_type, user=self.request.user)
        if not detail_view_tabs:
            detail_view_tabs = UserDetailViewTab.generate_default_for_user(content_type=content_type, user=self.request.user)

        context['detail_view_tabs'] = detail_view_tabs
        context['detail_links_form'] = DetailLinksSelectForm(content_type=content_type, user=self.request.user)


        # User context data
        context["user"] = self.request.user

        # Model context data
        context["model_name"] = self.model._meta.verbose_name
        context["model_name_plural"] = self.model._meta.verbose_name_plural
        context["content_type_id"] = ContentType.objects.get_for_model(self.model).pk
        context["model"] = self.model

        # URL context data
        context["model_dashboard_url"] = get_model_dashboard_view_url(self.model)
        context["create_view_url"] = get_create_view_url(self.model)
        context['update_view_url'] = get_update_view_url(self.model)
        context['list_view_url'] = get_list_view_url(self.model)
        context['detail_view_url'] = get_detail_view_url(self.model)
        context['bulk_upload_url'] = get_bulk_upload_view_url(self.model)

        try:
            if hasattr(self, 'object'):
                context['llm_args'] = 'content_type_id=' + str(context['content_type_id']) + ';object_id=' + str(self.object.pk)
        except:
            pass
        # Application fields context data
        context['application_fields'] = ApplicationField.objects.filter(content_type_id=context['content_type_id'])
        return context