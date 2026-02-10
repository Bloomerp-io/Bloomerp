from django.db.models.base import Model as Model
from django.contrib.auth import get_user_model

User = get_user_model()

class ProfileMixin:
    tabs = [
        {"name":"Details", "url":"users_my_profile_overview", "requires_pk":False},
        {"name":"Change password", "url":"users_my_profile_change_password", "requires_pk":False},
    ]
    exclude_header = True

    extra_context = {"disable_tab_select":True, "tabs":tabs}

    def get_object(self):
        return User.objects.get(pk=self.request.user.pk)
    model = User