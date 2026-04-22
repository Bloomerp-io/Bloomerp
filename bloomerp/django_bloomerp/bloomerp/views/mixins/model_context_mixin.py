from bloomerp.models import ApplicationField, BloomerpModel
from bloomerp.utils.models import get_bulk_upload_view_url, get_create_view_url, get_detail_view_url, get_list_view_url, get_model_dashboard_view_url, get_update_view_url


from django.contrib.contenttypes.models import ContentType


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