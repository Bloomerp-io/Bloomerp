from django.urls import reverse

from bloomerp.models.access_control.field_policy import FieldPolicy
from bloomerp.models.access_control.row_policy import RowPolicy
from bloomerp.models.application_field import ApplicationField
from bloomerp.tests.base import BaseBloomerpModelTestCase
from django.contrib.contenttypes.models import ContentType

class TestCreateView(BaseBloomerpModelTestCase):
    """
    This test suite contains tests related the create component
    """

    def get_url(self) -> str:
        return reverse("customers_create")


    def add_global_permission(self):
        """
        Adds global permission to user
        """
        pass

    def add_field_permission(self, fields:list[str], perms:list[str]):
        """
        Adds field permission to user
        """
        # 1. Get all the necessary data
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        fields = ApplicationField.objects.filter(
            fields__in=fields
        )
        rule = {}
        for field in fields:
            rule[str(field.id)] = perms

        # 2. Create the policy
        field_policy = FieldPolicy.objects.create(
            content_type=content_type,
            name="Xxx",
            rule=rule
        )


        row_policy = RowPolicy.objects.create(
            content_type=content_type,
            name="XYZ",
        )
        
        # 3. 




    # ------------------------
    # GET REQUESTS
    # ------------------------
    def test_GET_with_query_parameters_will_pre_fill_value(self):
        """
        Tests whether calling the view with get parameters
        will prefill the form
        """
        # 1. Get url
        url = self.get_url()

        # 2. Add parameters
        url += "?first_name=XYZ"

        # 3. Call the endpoint
        self.client.force_login(self.admin_user)
        response = self.client.get(url)

        # 4. Check whether first name is filled
        self.assertContains(response, 'value="XYZ"', html=False)

    
    def test_GET_with_non_admin_user_without_permission(self):
        """
        Tests whether calling the view without any permissions
        returns a 404.
        """
        # 1. Get the url
        url = self.get_url()

        # 2. Call the endpoint
        self.client.force_login(self.normal_user)
        response = self.client.get(url)

        # 3. Make sure there are no inputs on the page


    def test_GET_with_non_admin_user_with_permission_to_fields(self):
        """
        Tests whether a user who has access to all the necessary
        fields has access to the different 
        """
    







