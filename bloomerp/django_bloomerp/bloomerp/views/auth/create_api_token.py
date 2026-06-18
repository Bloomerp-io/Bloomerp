from bloomerp.forms.model_form import bloomerp_modelform_factory
from bloomerp.models.api_key import ApiKey
from bloomerp.router import router
from bloomerp.views.base import BaseBloomerpView
from django.db import transaction
from django.views.generic.edit import FormView


@router.register(
    path="create",
    route_type="model",
    name="Create API Key",
    url_name="add",
    models=ApiKey,
    override=True
)
class CreateApiTokenView(BaseBloomerpView, FormView):
    template_name = "views/auth/create_api_token.html"
    model = ApiKey
    raw_token: str | None = None
    object: ApiKey | None = None

    def has_permission(self):
        return bool(self.request.user and self.request.user.is_authenticated)
    
    def get_form_class(self):
        return bloomerp_modelform_factory(ApiKey, fields=["name", "expires_at"])
    
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["raw_token"] = self.raw_token
        ctx["object"] = self.object
        return ctx

    def form_valid(self, form):
        with transaction.atomic():
            api_key = form.save(commit=False)
            api_key.account = self.request.user
            api_key.created_by = self.request.user
            api_key.updated_by = self.request.user
            self.raw_token = api_key.set_token()
            api_key.save()
        self.object = api_key

        self.add_message("API key created successfully.", "success")
        return self.render_to_response(self.get_context_data(form=self.get_form_class()()))
