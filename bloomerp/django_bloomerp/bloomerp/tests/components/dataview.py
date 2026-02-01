from django.urls import reverse
from bloomerp.tests.base import BaseBloomerpModelTestCase
from bloomerp.models import ApplicationField

class TestDataView(BaseBloomerpModelTestCase):
    def extendedSetup(self):
        return super().extendedSetup()    
        
    def test_update_field_get(self):
        """
        This test checks whether it's possible to update fields
        """
        # Login the client
        self.client.force_login(self.admin_user)
        
        # Get the customer object
        customer = self.CustomerModel.objects.first()
        
        # Create url
        url = reverse(
            viewname="components_dataview_edit_field", 
            kwargs={
                    "application_field_id" : ApplicationField.get_by_field(self.CustomerModel, "first_name").id,
                    "object_id" : str(customer.id)
                }
            )
        
        # Send GET request to the URL
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        
        # Check if the response contains an input element
        self.assertContains(response, '<input', html=False)
    
    def test_update_field_post_success(self):
        """
        This test checks whether it's possible to update fields via POST
        """
        # Login the client
        self.client.force_login(self.admin_user)
        
        # Get the customer object
        customer = self.CustomerModel.objects.first()
        
        # Get the application field for first_name
        application_field = ApplicationField.get_by_field(self.CustomerModel, "first_name")
        
        # Create url
        url = reverse(
            viewname="components_dataview_edit_field", 
            kwargs={
                    "application_field_id" : application_field.id,
                    "object_id" : str(customer.id)
                }
            )
        
        # Send POST request to the URL
        new_first_name = "UpdatedName"
        response = self.client.post(url, data={application_field.field: new_first_name})
        self.assertEqual(response.status_code, 200)
        
        # Refresh the customer object from the database
        customer.refresh_from_db()
        
        # Check if the first_name field was updated
        self.assertEqual(customer.first_name, new_first_name)
        
        print(response.content)