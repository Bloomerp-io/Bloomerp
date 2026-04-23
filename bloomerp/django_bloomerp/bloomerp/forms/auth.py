from django import forms
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.utils.translation import gettext_lazy as _

from bloomerp.auth import get_interactive_auth_settings, get_login_field_label
from bloomerp.models import AbstractBloomerpUser

User:AbstractBloomerpUser = get_user_model()

# ---------------------------------
# User Detail View Preference Form
# ---------------------------------
from bloomerp.models import UserDetailViewPreference, ApplicationField
class UserDetailViewPreferenceForm(forms.ModelForm):
    class Meta:
        model = UserDetailViewPreference
        fields = '__all__'

    selected = forms.BooleanField(required=False)
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Set initial value of selected field to True
        if self.instance and self.instance.pk:
            self.fields['selected'].initial = True

    @property
    def application_field_str(self):
        try:
            return ApplicationField.objects.get(pk=self.initial.get('application_field')).field.replace(' ','_').capitalize()
        except:
            print('Error getting application field', self.initial.get('application_field'))
            return 'Unknown'


    def save(self, *args, **kwargs):
        if self.cleaned_data.get('selected'):
            return super().save(*args, **kwargs)
        else:
            if self.instance.pk:
                self.instance.delete()
            return None


# ---------------------------------
# User selection form
# ---------------------------------
class UserSelectionForm(forms.Form):
    users = forms.ModelChoiceField(
        queryset=User.objects.all(),
        empty_label="Select a user",  # Optional: Display a default label
        required=False
    )


# ---------------------------------
# User Creation Form
# ---------------------------------
from django.contrib.auth.forms import UserCreationForm


def get_user_creation_fields(user_model:type[AbstractBloomerpUser]) -> tuple[str, ...]:
    ordered_fields = [user_model.USERNAME_FIELD, *getattr(user_model, "REQUIRED_FIELDS", [])]
    return tuple(dict.fromkeys(ordered_fields))


class BloomerpUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = get_user_creation_fields(User)


class BloomerpAuthenticationForm(AuthenticationForm):
    error_messages = {
        "invalid_login": _(
            "Please enter a correct %(identifier)s and password. Note that both fields may be case-sensitive."
        ),
        "inactive": _("This account is inactive."),
    }

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        identifier_label = get_login_field_label()
        self.fields["username"].label = identifier_label
        self.fields["username"].widget.attrs.update(
            {
                "placeholder": identifier_label,
                "autocomplete": "email" if get_interactive_auth_settings().login_identifier == "email" else "username",
            }
        )

    def clean(self):
        identifier = self.cleaned_data.get("username")
        password = self.cleaned_data.get("password")

        if identifier is not None and password:
            credentials = self._get_credentials(identifier, password)
            self.user_cache = authenticate(self.request, **credentials)
            if self.user_cache is None:
                raise self.get_invalid_login_error()
            self.confirm_login_allowed(self.user_cache)

        return self.cleaned_data

    def _get_credentials(self, identifier: str, password: str) -> dict[str, object]:
        interactive_settings = get_interactive_auth_settings()
        username_field = getattr(User, "USERNAME_FIELD", "username")
        credentials: dict[str, object] = {"password": password}

        if interactive_settings.login_identifier == "email":
            user = User._default_manager.filter(email__iexact=identifier).first()
            credentials[username_field] = (
                getattr(user, username_field) if user is not None else identifier
            )
            return credentials

        credentials[username_field] = identifier
        return credentials

    def get_invalid_login_error(self):
        return forms.ValidationError(
            self.error_messages["invalid_login"],
            code="invalid_login",
            params={"identifier": get_login_field_label().lower()},
        )
