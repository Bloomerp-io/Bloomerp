
from django.test import TestCase
from bloomerp.forms.auth import UserDetailViewPreferenceForm

class BloomerpFormsTests(TestCase):
    def test_user_detail_view_preference_form(self):
        form_data = {'field1': 'value1', 'field2': 'value2'}
        form = UserDetailViewPreferenceForm(data=form_data)
        self.assertTrue(form.is_valid())