from typing import Any
from django.views.generic.detail import DetailView
from bloomerp.views.mixins import BloomerpModelContextMixin, HtmxMixin
from bloomerp.router import router

class BloomerpBaseDetailView(HtmxMixin, BloomerpModelContextMixin, DetailView):
    htmx_template = "bloomerp_htmx_base_view.html"
    tabs = None
    exclude_header = False
    
    def get_context_data(self, **kwargs: Any) -> dict:
        context = super().get_context_data(**kwargs)
        context["exclude_header"] = self.exclude_header
        if self.tabs:
            context["tabs"] = self.tabs
            
        context["tabs"] = self.get_tabs()
        return context

    def get_tabs(self):
        tabs = []
        for route in router.filter(
            model=self.model,
            route_type="detail",
        ):
            if route.nr_of_args() == 1:
                tabs.append(
                    {
                        "name" : route.name,
                        "url" : route.url_name,
                        "path" : route.path,
                        "requires_pk" : True
                    }
                )
        return tabs
        
        
        