from django.shortcuts import render
from django.views.generic import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.contenttypes.models import ContentType
from bloomerp.models.users import Bookmark
from bloomerp.views.mixins import HtmxMixin
from registries.route_registry import router


@router.register(
    path="user-bookmarks",
    name="Bookmarks for user",
    url_name="user_bookmarks",
    description="Bookmarks for user",
    route_type="list",
    models=[Bookmark],
)
class BloomerpBookmarksView(LoginRequiredMixin, HtmxMixin, View):
    template_name = "list_views/bloomerp_bookmarks_view.html"
    model = None

    def get_permission_required(self):
        return [f"{self.model._meta.app_label}.view_{self.model._meta.model_name}"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["content_type_id"] = ContentType.objects.get_for_model(self.model).pk
        context["initial_query"] = "user=" + str(self.request.user.pk)
        return context

    def get(self, request, *args, **kwargs):
        context = self.get_context_data()
        return render(request, self.template_name, context)
