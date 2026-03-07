from bloomerp.forms.core import BloomerpModelForm
from django.shortcuts import redirect
from django.http import HttpResponse
from django.forms.models import modelform_factory
from bloomerp.models import ApplicationField
from django.views.generic import DetailView, UpdateView
from bloomerp.modules.definition import ModuleConfig
from django.urls import reverse
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
from bloomerp.models import BloomerpModel
from bloomerp.forms.model_form import bloomerp_modelform_factory
from bloomerp.router import router
from bloomerp.router import RouteType


class HtmxMixin:
    """Updates the template name based on the request.htmx attribute."""
    htmx_template = 'bloomerp_htmx_base_view.html'
    htmx_addendum_template = 'htmx_addendum.html'
    base_detail_template = 'detail_views/bloomerp_base_detail_view.html'
    htmx_detail_target = 'detail-view-content'
    htmx_main_target = 'main-content'
    htmx_skip_addendum_target = 'data-table-detail-pane'
    is_detail_view = False
    include_padding = True
    
    # Some other args
    module : ModuleConfig = None

    def _normalize_route_type(self, route_type) -> str | None:
        if isinstance(route_type, RouteType):
            return route_type.value
        if isinstance(route_type, str):
            return route_type.lower()
        return None

    def _resolve_current_route(self):
        resolver_match = getattr(self.request, "resolver_match", None)
        if not resolver_match or not resolver_match.url_name:
            return None

        try:
            for route in router.get_routes():
                if route.url_name == resolver_match.url_name:
                    return route
        except Exception:
            return None
        return None

    def _resolve_route_title(self) -> str:
        route = self._resolve_current_route()
        if route and getattr(route, "name", None):
            return route.name
        return "Home"

    def _resolve_detail_object(self, context: dict):
        if context.get("object") is not None:
            return context.get("object")

        if not hasattr(self, "get_object"):
            return None

        try:
            return self.get_object()
        except Exception:
            return None

    def _build_breadcrumb_items(self, context: dict) -> list[dict]:
        items: list[dict] = [
            {
                "text": "Home",
                "url": "/",
                "active": False,
            }
        ]

        route = self._resolve_current_route()
        if not route:
            items[0]["active"] = True
            return items

        route_type = self._normalize_route_type(route.route_type)
        module = getattr(route, "module", None)
        model = getattr(route, "model", None)
        route_name = route.name or "Route"
        module_url = f"/{module.id.lower()}/" if module else None

        if route_type == RouteType.APP.value:
            items.append({"text": route_name, "url": self.request.path, "active": True})
            return items

        if module:
            is_module_home = bool(route.path and route.path == module_url)
            items.append(
                {
                    "text": module.name,
                    "url": module_url,
                    "active": is_module_home,
                }
            )
            if is_module_home:
                return items

        if route_type == RouteType.MODULE.value:
            items.append({"text": route_name, "url": self.request.path, "active": True})
            return items

        if model:
            model_text = model._meta.verbose_name.title()
            try:
                model_url = get_list_view_url(model)
            except Exception:
                model_url = self.request.path
            items.append({"text": model_text, "url": model_url, "active": False})

        if route_type == RouteType.MODEL.value:
            items.append({"text": route_name, "url": self.request.path, "active": True})
            return items

        if route_type == RouteType.DETAIL.value:
            detail_object = self._resolve_detail_object(context)
            if detail_object is not None:
                object_text = str(detail_object)
                try:
                    object_url = reverse(get_detail_view_url(detail_object.__class__), kwargs={"pk": detail_object.pk})
                except Exception:
                    object_url = self.request.path
                items.append({"text": object_text, "url": object_url, "active": False})

            items.append({"text": route_name, "url": self.request.path, "active": True})
            return items

        items.append({"text": route_name, "url": self.request.path, "active": True})
        return items
    
    
    def get_context_data(self, **kwargs:Any) -> dict:
        import random 
        try:
            context = super().get_context_data(**kwargs)
        except AttributeError:
            # If the super class does not have a get_context_data method
            context = {}

        base_template_name = self.template_name
        is_detail_request = self.is_detail_view or isinstance(self, DetailView) or isinstance(self, UpdateView)

        
        
        # ---------------------
        # NORMAL REQUEST
        # ---------------------
        if not self.request.htmx or self.request.htmx.history_restore_request:
            if is_detail_request:
                context['include_main_content'] = self.base_detail_template
                context['include_detail_content'] = base_template_name
                context['template_name'] = self.base_detail_template
            else:
                context['template_name'] = base_template_name
            self.template_name = self.htmx_template
        
        # ---------------------
        # HTMX REQUEST
        # ---------------------
        else:
            htmx_target = getattr(self.request.htmx, 'target', None)

            if htmx_target == self.htmx_skip_addendum_target:
                context['template_name'] = base_template_name
                self.template_name = base_template_name
                context["rand_int"] = random.randint(0,10000)
                context["route_title"] = self._resolve_route_title()
                context["breadcrumbs"] = self._build_breadcrumb_items(context)
                return context

            context['include_addendum_oob'] = (
                is_detail_request and htmx_target == self.htmx_detail_target
            )

            # Check the target of htmx
            if htmx_target == self.htmx_main_target:
                if is_detail_request:
                    # In this case, we are dealing with a detail view
                    context['include_detail_content'] = base_template_name
                    context['template_name'] = self.base_detail_template
                else:
                    context['template_name'] = base_template_name
            else:
                context['template_name'] = base_template_name

            self.template_name = self.htmx_addendum_template
                
        
        context["rand_int"] = random.randint(0,10000)
        context["route_title"] = self._resolve_route_title()
        context["breadcrumbs"] = self._build_breadcrumb_items(context)
        
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

    # TODO: this needs to be changed becauauas
    
    def get_form_kwargs(self) -> dict:
        kwargs = super().get_form_kwargs()
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
        return bloomerp_modelform_factory(
            model_cls=self.model,
            fields="__all__",
        )


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

        
        # Application fields context data
        context['application_fields'] = ApplicationField.objects.filter(content_type_id=context['content_type_id'])
        
        # Tabs
        return context
    
    
