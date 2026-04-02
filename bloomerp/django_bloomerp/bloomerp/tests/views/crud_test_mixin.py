
from django.http import HttpResponse

from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from bloomerp.models.access_control.row_policy import RowPolicy
from bloomerp.models.access_control.row_policy_rule import RowPolicyRule
from bloomerp.models.access_control.field_policy import FieldPolicy
from bloomerp.models.access_control.policy import Policy
from bloomerp.models.users.user import User
from bloomerp.tests.base import BaseBloomerpModelTestCase
from bs4 import BeautifulSoup

class CrudViewTestMixin(BaseBloomerpModelTestCase):
    
    def field_has_value(self, response:HttpResponse, field_name:str, value:str) -> bool:
        """
        Test whether a certain field has a value.
        """
        # 1. Find the div which contains name = first_name using BeautifulSoup -> should be an input element
        soup = BeautifulSoup(response.content, 'html.parser')
        input_element = soup.find('input', {'name': field_name})
        
        # 2. Check if the value of the input element is equal to the value parameter
        if input_element and input_element.get('value') == value:
            return True
        return False
    

    def get_url(self) -> str:
        """
        This should return the URL that is being tested.
        """
        raise NotImplementedError("Subclasses must implement get_url method")
    

    def grant_global_page_access(self, user:User, permission_str:str) -> Policy:
        """
        Grants the user with global access to the page.
        """
        permission = Permission.objects.get(codename=permission_str)
        content_type = permission.content_type

        row_policy = RowPolicy.objects.create(
            content_type=content_type,
            name=f"{permission_str}_row_policy",
        )
        field_policy = FieldPolicy.objects.create(
            content_type=content_type,
            name=f"{permission_str}_field_policy",
            rule={},
        )

        page_access_policy = Policy.objects.create(
            name=f"{permission_str}_access_policy",
            row_policy=row_policy,
            field_policy=field_policy,
        )

        page_access_policy.assign_user(user)
        page_access_policy.global_permissions.add(permission)

        return page_access_policy


    # ---------------------------
    # Shared test cases
    # ---------------------------

    def test_user_global_access(self):
        """
        This tests whether the user has global access to the view
        based on the given permission.
        """
        pass
    
    def test_POST_request_with_field_error_returns_error(self):
        """
        This tests whether a POST request with invalid data returns errors.
        It also tests whether the specific errors are shown for the fields that have errors.
        """
        # 1. Create payload with invalid data

        # 2. Send POST request to the view

        # 3. Check that the field with the invalid data shows an error message in the response

        # 4. Check that the database does not contain any object with the given data
        pass

    def test_POST_request_with_invalid_global_data_returns_error(self):
        """
        This tests whether a POST request with invalid global data (e.g. validation error not fulfilled) returns errors.
        It also tests whether the specific errors are shown for the global data that have errors.
        """
        # 1. Create payload with invalid data

        # 2. Send POST request to the view

        # 3. Check that the response contains the error messages for the invalid data

        # 4. Check that the database does not contain any object with the given data
        pass

    # ---------------------------
    # Frontend tests
    # ---------------------------

    def test_inserting_values_and_pushing_reset_button_clears_values(self):
        """
        This tests whether inserting values into the form and pushing the reset button clears the values.
        """
        # TODO: Needs to be implemented usign Playwright or Selenium
        
        # 1. Insert values "first_name" Lisa

        # 2. Click the reset button

        # 3. Check that "first_name" is empty
        pass

    def test_inserting_values_and_clicking_back_button_clears_one_value(self):
        """
        This tests whether inserting values into the form and pushing the back button clears one value.
        """
        # TODO: Needs to be implemented usign Playwright or Selenium
        
        # 1. Insert values "first_name" Lisa

        # 2. Click the back button

        # 3. Check that "first_name" is just Lis and not Lisa anymore
        pass

    def test_save_button_submits_form(self):
        """
        This tests whether inserting values into the form and pushing the save button submits the form.
        """
        # TODO: Needs to be implemented usign Playwright or Selenium

        # 1. Insert values "first_name" Lisa

        # 2. Click the save button

        # 3. Check that the form is submitted and the object is created with first_name Lisa
        pass
