from django import forms
from bloomerp.models import AbstractBloomerpUser
from django.contrib.auth import get_user_model
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
class BloomerpUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = UserCreationForm.Meta.fields + ('email',)

