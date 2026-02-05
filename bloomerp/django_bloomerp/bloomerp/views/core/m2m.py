from django.contrib.auth.mixins import PermissionRequiredMixin
from django.contrib.contenttypes.models import ContentType
from django.forms.models import modelform_factory
from django.db.models import Model
from bloomerp.models.application_field import ApplicationField
from bloomerp.models.files import File
from bloomerp.forms.core import BloomerpModelForm
from bloomerp.views.mixins import HtmxMixin
from shared_utils.router.view_router import _get_name_or_slug
from .base_detail import BloomerpBaseDetailView
from bloomerp.router import router

# ---------------------------------
# Bloomerp many-to-many detail view
# ---------------------------------
# from django.db.models.fields.reverse_related import ManyToManyRel, ManyToOneRel
# from bloomerp.models import Comment
# def get_view_parameters(model:Model):
#     params_list = []
#     model_name = model._meta.verbose_name

#     fields = model._meta.get_fields()

#     if model in [File, Comment]:
#         return False

#     for field in fields:
#         # Skip fields that
#         if field.name in ['created_by','updated_by']:
#             continue

#         if field.get_internal_type() == 'ManyToManyField':
#             if field.related_model in [Comment, File]:
#                 continue

#             if type(field) == ManyToManyRel:
#                 params_dict = {
#                     'path' : f'{_get_name_or_slug(field.related_model, slug=True)}',
#                     'name' : f'{field.related_model._meta.verbose_name_plural.capitalize()}',
#                     'url_name' : f'{_get_name_or_slug(field.related_model)}_relationship',
#                     'model' : model,
#                     'route_type' : 'detail',
#                     'description' : f'{field.related_model._meta.verbose_name_plural.capitalize()} relationship for {model_name}',
#                     'args': {
#                         'related_model':field.related_model,
#                         'related_model_attribute' : field.name,
#                         'reversed':True,
#                         'related_model_field' : field.remote_field.name
#                     }
#                 }

#             else:
#                 if field.related_model in [Comment, File]:
#                     continue

#                 params_dict = {
#                     'path' : f'{field.name}/',
#                     'name' : f'{field.verbose_name.capitalize()}',
#                     'url_name' : field.name + '_relationship',
#                     'description' : f'{field.verbose_name.capitalize()} relationship for {model_name}',
#                     'model' : model,
#                     'route_type' : 'detail',
#                     'args' : {
#                         'related_model':field.related_model,
#                         'related_model_attribute':True,
#                         'reversed':False,
#                         'related_model_field':field.remote_field.name
#                         }
#                 }

#             params_list.append(params_dict)

#         elif type(field) == ManyToOneRel:
#             if field.related_model in [Comment, File]:
#                 return False

#             params_dict = {
#                 'path' : f'{_get_name_or_slug(field.related_model, slug=True)}',
#                 'name' : f"{field.name.capitalize().replace('_',' ')}",
#                 'url_name' : f'{_get_name_or_slug(field.related_model)}_relationship',
#                 'model' : model,
#                 'route_type' : 'detail',
#                 'description' : f"{field.name.capitalize().replace('_',' ')} relationship for {model_name}",
#                 'args': {
#                     'related_model':field.related_model,
#                     'related_model_attribute' : field.name,
#                     'reversed':False,
#                     'related_model_field' : field.remote_field.name
#                 }
#             }

#             params_list.append(params_dict)

#     return params_list


# @router.register(from_func=get_view_parameters)
# class BloomerpDetailM2MView(PermissionRequiredMixin, BloomerpBaseDetailView):
#     template_name : str = "detail_views/bloomerp_detail_m2m_view.html"
#     model : Model = None
#     related_model : Model = None
#     related_model_attribute : str = None
#     reversed : bool = None
#     related_model_field : str = None

#     def get_permission_required(self):
#         foreign_view_permission = f"{self.related_model._meta.app_label}.view_{self.related_model._meta.model_name}"
#         model_view_permission = (
#             f"{self.model._meta.app_label}.view_{self.model._meta.model_name}"
#         )
#         return [foreign_view_permission, model_view_permission]

#     def get_context_data(self, **kwargs: Any) -> dict:
#         context = super().get_context_data(**kwargs)

#         # Construct initial query
#         initial_query = f'{self.related_model_field}={self.get_object().pk}'

#         # Get application fields for the foreign model
#         application_fields = ApplicationField.get_for_model(self.related_model)
#         if self.reversed == False:
#             # Create form
#             Form = modelform_factory(model=self.related_model, fields='__all__', form=BloomerpModelForm)

#             form = Form(model=self.related_model, user=self.request.user, initial={self.related_model_field:self.get_object().pk})

#             context['form'] = form

#         # Set content_type_id
#         context['foreign_content_type_id'] = ContentType.objects.get_for_model(self.related_model).pk
#         context['foreign_model_attribute'] = self.related_model_attribute
#         context['object'] = self.object
#         context['application_fields'] = application_fields
#         context['initial_query'] = initial_query
#         context['reversed'] = self.reversed
#         context['related_model'] = self.related_model
#         context['related_model_name_singular'] = self.related_model._meta.verbose_name
#         context['related_model_name_plural'] = self.related_model._meta.verbose_name_plural
#         return context
