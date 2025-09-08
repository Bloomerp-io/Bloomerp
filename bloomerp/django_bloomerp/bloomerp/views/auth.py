from typing import Any
from django.db.models.base import Model as Model
from django.forms import formset_factory
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render, redirect
from django.urls import reverse, reverse_lazy
from django.contrib import messages
from bloomerp.forms.auth import UserDetailViewPreferenceForm
from bloomerp.forms.core import ListViewFieldsSelectForm
from django.contrib.contenttypes.models import ContentType
from django.core.paginator import Paginator
from bloomerp.views.mixins import HtmxMixin
from bloomerp.models import (UserDetailViewPreference,ApplicationField)
from bloomerp.utils.models import model_name_plural_underline
from django.contrib.auth.mixins import PermissionRequiredMixin
from bloomerp.utils.router import BloomerpRouter
from bloomerp.views.mixins import HtmxMixin, BloomerpModelContextMixin
from bloomerp.views.mixins import BloomerpModelFormViewMixin
from bloomerp.views.core import BloomerpBaseDetailView
from django.contrib.auth.forms import PasswordChangeForm, AdminPasswordChangeForm
from django.views.generic.edit import FormView, UpdateView
from django.contrib.auth import update_session_auth_hash
from django.forms import modelformset_factory
from bloomerp.forms.auth import UserDetailViewPreferenceForm
import time

router = BloomerpRouter()

from django.contrib.auth import get_user_model
User = get_user_model()

class ProfileMixin:
    tabs = [
        {"name":"Details", "url":"users_my_profile_overview", "requires_pk":False},
        {"name":"Change password", "url":"users_my_profile_change_password", "requires_pk":False},
        {"name":"List view preferences", "url":"users_my_profile_list_view_preference","requires_pk":False},
        {"name":"Detail view preferences", "url":"users_my_profile_detail_view_preference","requires_pk":False}
    ]
    exclude_header = True

    extra_context = {"disable_tab_select":True, "tabs":tabs}

    def get_object(self):
        return User.objects.get(pk=self.request.user.pk)
    model = User




@router.bloomerp_route(
    path="my-profile/",
    models=User,
    route_type="list",
    name="Profile",
    description="Overview of profile",
    url_name="my_profile_overview"
)
class BloomerpProfileView(BloomerpModelFormViewMixin, ProfileMixin, HtmxMixin, BloomerpModelContextMixin, UpdateView):
    template_name = 'auth_views/profile_overview.html'
    fields = ['first_name', 'last_name', 'date_view_preference', 'datetime_view_preference', 'avatar']
    success_url = reverse_lazy('users_my_profile_overview')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['instance'] = self.request.user
        return kwargs

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        form = self.get_form()
        if form.is_valid():
            form.save()
            messages.success(request, 'Profile updated successfully.')
            return redirect(self.success_url)
        else:
            return self.form_invalid(form)
    
    

@router.bloomerp_route(
    path="my-profile/reset-password/",
    models=User,
    route_type="list",
    name="Reset password",
    description="Reset password for a user",
    url_name="my_profile_change_password"
)
class BloomerpProfilePasswordResetView(ProfileMixin, BloomerpBaseDetailView, FormView):
    template_name = 'auth_views/profile_password_reset.html'
    form_class = PasswordChangeForm
    success_url = reverse_lazy('users_my_profile_overview')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form:PasswordChangeForm):
        self.object = self.get_object()
        form.save()
        update_session_auth_hash(self.request, form.user)  # Prevents logout
        return super().form_valid(form)    
    
    def form_invalid(self, form):
        self.object = self.get_object()
        return super().form_invalid(form)
    

@router.bloomerp_route(
    path="my-profile/list-view-preference/",
    models=User,
    route_type="list",
    name="List view preference",
    description="List view preference for a user",
    url_name="my_profile_list_view_preference"
)
class UserListViewPreferenceView(ProfileMixin, BloomerpBaseDetailView):
    template_name = 'user_views/list_view_preference_view.html'
    permission_required = ['users.change_userlistviewpreference']
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        content_type_list = ContentType.objects.all()
        content_type_id = self.request.GET.get('content_type_id',None)

        # Necessary context data
        context['url_name'] = 'users_my_profile_list_view_preference'
        context['title'] = 'List view preferences'
        
        if content_type_id:
            context['selected_content_type'] = ContentType.objects.get(pk=int(content_type_id))

            form = ListViewFieldsSelectForm(
                content_type=ContentType.objects.get(pk=content_type_id),
                user=self.request.user)
            
            context['form'] = form

        context['content_type_list'] = content_type_list
        return context

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        content_type_id = request.GET.get('content_type_id',None)
        return_to = request.GET.get('return_to',None)

        form = ListViewFieldsSelectForm(
                content_type=ContentType.objects.get(pk=content_type_id),
                user=self.request.user,
                data=request.POST
            )
        
        if form.is_valid():
            form.save()
            messages.success(self.request, 'Preferences saved successfully.')
            if return_to:
                return redirect(return_to)
            else:
                return redirect(reverse('users_my_profile_list_view_preference') + f'?content_type_id={content_type_id}')
        else:
            return render(request, self.template_name, {'form': form})


# ---------------------------
# USER DETAIL VIEW PREFERENCE VIEW
# ---------------------------
from django.views.generic.edit import FormView
@router.bloomerp_route(
    path="my-profile/detail-view-preferences/",
    models=User,
    route_type="list",
    name="Detail view preference",
    description="Detail view preference for a user",
    url_name="my_profile_detail_view_preference"
    )
class UserDetailViewPreferenceView(ProfileMixin, BloomerpBaseDetailView):
    template_name = 'user_views/bloomerp_detail_view_preference_view.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        selected_content_type = self.get_content_type()

        # Necessary context data
        context['url_name'] = 'users_my_profile_detail_view_preference'
        context['title'] = 'Detail view preferences'

        if selected_content_type and self.request.method == 'GET':
            formset = self.get_formset(content_type_id=selected_content_type.id)
            context['formset'] = formset


        context['return_to'] = self.request.GET.get('return_to', None)
        context['selected_content_type'] = selected_content_type
        return context

    def post(self, request, *args, **kwargs):
        content_type = self.get_content_type()
        context = self.get_context_data()

        if not content_type:
            return self.form_invalid_response()

        formset = self.get_formset(content_type_id=content_type.pk, data=request.POST)

        if formset.is_valid():
            formset.save()

            if request.GET.get('return_to', None):
                return redirect(request.GET.get('return_to'))

            return redirect(reverse('users_my_profile_detail_view_preference') + f'?content_type_id={content_type.pk}')
        else:
            context['formset'] = formset
            return render(request, self.template_name, context)

    def get_formset(self, content_type_id, data=None):
        """Returns a formset for the UserDetailViewPreference model."""
        user = self.request.user
        application_fields = ApplicationField.objects.filter(
            content_type=content_type_id
        ).order_by('field')

        n = application_fields.count()
        selected_content_type = ContentType.objects.get(pk=content_type_id)
        queryset = UserDetailViewPreference.objects.filter(
            user=user,
            application_field__content_type=selected_content_type
        ).order_by('application_field__field')

        # Prepare initial data for missing application fields
        initial_data = [
            {
                'application_field': af.pk,
                'user': user.pk,
                'position': 'LEFT',
                'selected': False,
                'application_field_str': af.field.replace('_', ' ').capitalize()
            }
            for af in application_fields if not queryset.filter(application_field=af).exists()
        ]
    
        formset_factory = modelformset_factory(
            UserDetailViewPreference,
            form=UserDetailViewPreferenceForm,
            fields=('application_field', 'position', 'selected', 'user', 'id'),
            min_num=n,
            max_num=n
        )

        return formset_factory(queryset=queryset, initial=initial_data, data=data)

    def get_content_type(self):
        """Retrieves the content type based on the GET parameter."""
        if self.request.method == 'POST':
            content_type_id = self.request.POST.get('content_type_id', None)
        else:
            content_type_id = self.request.GET.get('content_type_id', None)
        return ContentType.objects.get(pk=content_type_id) if content_type_id else None


# ---------------------------
# USER CREATE VIEW
# ---------------------------
from bloomerp.forms.auth import BloomerpUserCreationForm
from django.contrib.messages.views import SuccessMessageMixin
@router.bloomerp_route(
    path="create",
    name="Create user",
    url_name="add",
    description="Create a new object from User",
    route_type="list",
    models=User
)
class UserCreateView(
        PermissionRequiredMixin, 
        SuccessMessageMixin,
        HtmxMixin,
        FormView):
    template_name = "create_views/bloomerp_create_view.html"
    fields = None
    model = None
    exclude = []
    success_message = "Object was created successfully."
    form_class = BloomerpUserCreationForm
    success_url = reverse_lazy("users_list")


    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["model_name"] = self.model._meta.verbose_name
        context["model_name_plural"] = self.model._meta.verbose_name_plural
        context["list_view_url"] = model_name_plural_underline(self.model) + "_list"
        context["model"] = self.model
        return context

    def form_valid(self, form):
        form.save()
        return super().form_valid(form)

    def get_permission_required(self):
        return [f"{self.model._meta.app_label}.add_{self.model._meta.model_name}"]

    def get_success_message(self, cleaned_data):
        return f"User was created successfully."



# ---------------------------
# ADMIN RESET PASSWORD VIEW
# ---------------------------
from django.contrib.auth.mixins import UserPassesTestMixin
@router.bloomerp_route(
    path='reset-password/',
    models=[User],
    route_type='detail',
    name='Reset password for user',
    url_name='reset_password_for_user',
    description='Reset password for a user'
)
class UserAdminPasswordResetView(UserPassesTestMixin, BloomerpBaseDetailView, FormView):
    template_name = 'auth_views/profile_password_reset.html'
    form_class = AdminPasswordChangeForm

    def test_func(self):
        return self.request.user.is_superuser

    def get_success_url(self):
        return self.get_object().get_absolute_url()

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.get_object()
        return kwargs

    def form_valid(self, form:AdminPasswordChangeForm):
        self.object = self.get_object()
        form.save()
        return super().form_valid(form)    
    
    def form_invalid(self, form):
        self.object = self.get_object()
        return super().form_invalid(form)
    


