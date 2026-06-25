from bloomerp.modules.definition import ModuleConfig, module_registry
from bloomerp.router import RouteType, router
from bloomerp.utils.models import get_detail_view_url, get_list_view_url


from django.urls import reverse
from django.views.generic import DetailView, UpdateView


import random
from typing import Any


class HtmxMixin:
    """Updates the template name based on the request.htmx attribute."""
    htmx_template = 'views/htmx_base.html'
    htmx_addendum_template = 'views/htmx_addendum.html'
    base_detail_template = 'views/generic/detail/base.html'
    htmx_detail_target = 'detail-view-content'
    htmx_main_target = 'main-content'
    htmx_include_addendum = True
    htmx_include_addendum_padding = True
    is_detail_view = None
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

    def get_htmx_include_addendum(self) -> bool:
        return self.htmx_include_addendum

    def should_include_htmx_addendum(self) -> bool:
        if not self.get_htmx_include_addendum():
            return False

        htmx_target = getattr(self.request.htmx, 'target', None)
        return htmx_target != 'data-table-detail-pane'

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
        module_key = (module.full_id or module.id) if module else None
        module_lineage = module_registry.get_lineage(module_key) if module_key else []
        module_url = f"/{module.route_path}/" if module and module.route_path else None

        if route_type == RouteType.APP.value:
            items.append({"text": route_name, "url": self.request.path, "active": True})
            return items

        if module_lineage:
            for index, lineage_module in enumerate(module_lineage):
                lineage_url = f"/{lineage_module.route_path}/" if lineage_module.route_path else self.request.path
                is_active = bool(route.path and route.path == lineage_url and index == len(module_lineage) - 1)
                items.append(
                    {
                        "text": lineage_module.name,
                        "url": lineage_url,
                        "active": is_active,
                    }
                )
            if route_type == RouteType.MODULE.value:
                items[-1]["active"] = True
                return items

        if route_type == RouteType.MODULE.value:
            items.append({"text": route_name, "url": self.request.path, "active": True})
            return items

        if model:
            model_text = (model._meta.verbose_name_plural or model._meta.verbose_name).title()
            try:
                model_url = reverse(get_list_view_url(model))
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

        # Check if we should add the detail view layout
        if isinstance(self.is_detail_view, bool):
            is_detail_request = self.is_detail_view
        else:
            is_detail_request = isinstance(self, DetailView) or isinstance(self, UpdateView)
        
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

            if not self.should_include_htmx_addendum():
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
        context["htmx_include_addendum_padding"] = self.htmx_include_addendum_padding
        return context